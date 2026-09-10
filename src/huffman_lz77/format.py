"""The on-disk container format: LZ77 tokens, entropy-coded with two
canonical Huffman codes (literal/length and distance), wrapped in a small
fixed-size header.

Layout::

    +----------+---------+-------------------+-------------+------------------------------+------------------------------+---------...
    | b"HZ77"  | version | original_size u64 | crc32 u32   | litlen code lengths (286 B)  | distance code lengths (30 B) | entropy-coded body
    | 4 bytes  | 1 byte  | 8 bytes, BE        | 4 bytes, BE | 1 byte per symbol, 0=unused  | 1 byte per symbol, 0=unused  | (see below)
    +----------+---------+-------------------+-------------+------------------------------+------------------------------+---------...

The crc32 field is a CRC-32 checksum of the *original, uncompressed* data
(the same algorithm gzip uses), verified after decoding. Without it, a
single flipped bit inside the entropy-coded body isn't guaranteed to be
caught: it can simply decode to a different — but equally valid-looking —
sequence of Huffman symbols that happens to produce the same total length,
which the original-size check alone can't distinguish from correct output.
A round-trip fuzz test that flipped individual bits across the body and
checked the *content*, not just the length, of the result is what caught
this gap during development.

The body is a sequence, for each LZ77 token, of:

* a literal byte: one Huffman-coded litlen symbol (0-255), or
* a match: one Huffman-coded litlen symbol (257-285, a length code) followed
  by that code's raw extra bits (if any), then one Huffman-coded distance
  symbol (0-29) followed by that code's raw extra bits (if any),

terminated by the litlen end-of-block symbol (256), then zero-padded to a
byte boundary. Decoding needs no explicit body length: it just reads litlen
symbols until it sees the end-of-block marker.
"""
from __future__ import annotations

import struct
import zlib

from .bitio import BitReader, BitWriter
from .huffman import CanonicalCode
from .lz77 import Literal, Match, tokenize
from .tables import (
    DISTANCE_ALPHABET_SIZE,
    DISTANCE_EXTRA_BITS,
    END_OF_BLOCK_SYMBOL,
    LENGTH_EXTRA_BITS,
    LITLEN_ALPHABET_SIZE,
    LITLEN_LENGTH_BASE_SYMBOL,
    code_to_distance,
    code_to_length,
    distance_to_code,
    length_to_code,
)

MAGIC = b"HZ77"
VERSION = 1
_HEADER = struct.Struct(">4sBQI")  # magic, version, original_size, crc32


class CorruptStreamError(ValueError):
    """Raised when a compressed blob is truncated, malformed, or has been
    tampered with in a way that's detectable during decoding."""


def compress(data: bytes, max_chain: int = 128) -> bytes:
    """Compress `data` into the HZ77 container format."""
    tokens = tokenize(data, max_chain=max_chain)

    litlen_freqs = [0] * LITLEN_ALPHABET_SIZE
    dist_freqs = [0] * DISTANCE_ALPHABET_SIZE
    litlen_freqs[END_OF_BLOCK_SYMBOL] += 1

    # Precompute each token's symbol(s) once so we don't re-derive the
    # length/distance codes a second time when writing the bitstream below.
    plan: list[tuple] = []
    for tok in tokens:
        if isinstance(tok, Literal):
            litlen_freqs[tok.byte] += 1
            plan.append(("lit", tok.byte))
        elif isinstance(tok, Match):
            len_idx, len_eb, len_val = length_to_code(tok.length)
            dist_idx, dist_eb, dist_val = distance_to_code(tok.distance)
            litlen_symbol = LITLEN_LENGTH_BASE_SYMBOL + len_idx
            litlen_freqs[litlen_symbol] += 1
            dist_freqs[dist_idx] += 1
            plan.append(("match", litlen_symbol, len_eb, len_val, dist_idx, dist_eb, dist_val))
        else:  # pragma: no cover - defensive
            raise TypeError(f"unknown token type: {tok!r}")

    litlen_code = CanonicalCode.from_frequencies(litlen_freqs)
    dist_code = CanonicalCode.from_frequencies(dist_freqs)
    _check_lengths_fit_in_a_byte(litlen_code.lengths, "literal/length")
    _check_lengths_fit_in_a_byte(dist_code.lengths, "distance")

    writer = BitWriter()
    for entry in plan:
        if entry[0] == "lit":
            litlen_code.encode_symbol(writer, entry[1])
        else:
            _, litlen_symbol, len_eb, len_val, dist_idx, dist_eb, dist_val = entry
            litlen_code.encode_symbol(writer, litlen_symbol)
            if len_eb:
                writer.write_bits(len_val, len_eb)
            dist_code.encode_symbol(writer, dist_idx)
            if dist_eb:
                writer.write_bits(dist_val, dist_eb)
    litlen_code.encode_symbol(writer, END_OF_BLOCK_SYMBOL)
    body = writer.getvalue()

    header = _HEADER.pack(MAGIC, VERSION, len(data), zlib.crc32(data) & 0xFFFFFFFF)
    return header + bytes(litlen_code.lengths) + bytes(dist_code.lengths) + body


def decompress(blob: bytes) -> bytes:
    """Decompress a blob previously produced by `compress`."""
    if len(blob) < _HEADER.size:
        raise CorruptStreamError("truncated container: missing header")
    magic, version, original_size, expected_crc32 = _HEADER.unpack(blob[: _HEADER.size])
    if magic != MAGIC:
        raise CorruptStreamError(f"not an HZ77 stream (bad magic {magic!r})")
    if version != VERSION:
        raise CorruptStreamError(f"unsupported container version {version} (expected {VERSION})")

    offset = _HEADER.size
    tables_end = offset + LITLEN_ALPHABET_SIZE + DISTANCE_ALPHABET_SIZE
    if len(blob) < tables_end:
        raise CorruptStreamError("truncated container: missing code length tables")
    litlen_lengths = list(blob[offset : offset + LITLEN_ALPHABET_SIZE])
    offset += LITLEN_ALPHABET_SIZE
    dist_lengths = list(blob[offset : offset + DISTANCE_ALPHABET_SIZE])
    offset = tables_end
    body = blob[offset:]

    litlen_code = CanonicalCode.from_lengths(litlen_lengths)
    dist_code = CanonicalCode.from_lengths(dist_lengths)

    reader = BitReader(body)
    out = bytearray()
    try:
        while True:
            symbol = litlen_code.decode_symbol(reader)
            if symbol == END_OF_BLOCK_SYMBOL:
                break
            if symbol < END_OF_BLOCK_SYMBOL:
                out.append(symbol)
                continue
            len_idx = symbol - LITLEN_LENGTH_BASE_SYMBOL
            len_eb = LENGTH_EXTRA_BITS[len_idx]
            len_val = reader.read_bits(len_eb) if len_eb else 0
            length = code_to_length(len_idx, len_val)

            dist_idx = dist_code.decode_symbol(reader)
            dist_eb = DISTANCE_EXTRA_BITS[dist_idx]
            dist_val = reader.read_bits(dist_eb) if dist_eb else 0
            distance = code_to_distance(dist_idx, dist_val)

            if distance <= 0 or distance > len(out):
                raise CorruptStreamError(
                    f"corrupt stream: match distance {distance} exceeds {len(out)} decoded bytes"
                )
            start = len(out) - distance
            for k in range(length):
                out.append(out[start + k])
    except EOFError as exc:
        raise CorruptStreamError("corrupt stream: ran out of bits mid-symbol") from exc
    except ValueError as exc:
        if isinstance(exc, CorruptStreamError):
            raise
        raise CorruptStreamError(str(exc)) from exc

    if len(out) != original_size:
        raise CorruptStreamError(
            f"decoded {len(out)} bytes but header declared {original_size} (corrupt stream)"
        )
    actual_crc32 = zlib.crc32(out) & 0xFFFFFFFF
    if actual_crc32 != expected_crc32:
        raise CorruptStreamError(
            f"CRC32 mismatch: expected {expected_crc32:#010x}, got {actual_crc32:#010x} "
            "(decoded bytes do not match the original data — corrupt stream)"
        )
    return bytes(out)


def _check_lengths_fit_in_a_byte(lengths: list[int], which: str) -> None:
    overflow = [l for l in lengths if l > 255]
    if overflow:
        raise ValueError(
            f"{which} alphabet produced a Huffman code length > 255 "
            f"(max was {max(overflow)}); this container format stores lengths "
            "as single bytes and cannot represent this input. This should "
            "only happen on adversarially constructed frequency distributions."
        )


def compress_file(input_path: str, output_path: str, max_chain: int = 128) -> tuple[int, int]:
    """Compress a file. Returns (original_size, compressed_size)."""
    with open(input_path, "rb") as f:
        data = f.read()
    blob = compress(data, max_chain=max_chain)
    with open(output_path, "wb") as f:
        f.write(blob)
    return len(data), len(blob)


def decompress_file(input_path: str, output_path: str) -> tuple[int, int]:
    """Decompress a file. Returns (compressed_size, original_size)."""
    with open(input_path, "rb") as f:
        blob = f.read()
    data = decompress(blob)
    with open(output_path, "wb") as f:
        f.write(data)
    return len(blob), len(data)
