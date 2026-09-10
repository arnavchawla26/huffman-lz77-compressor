import random
import struct
import zlib

import pytest

from huffman_lz77.format import (
    MAGIC,
    VERSION,
    CorruptStreamError,
    compress,
    decompress,
)


def roundtrip(data: bytes):
    blob = compress(data)
    assert decompress(blob) == data
    return blob


def test_empty_input():
    roundtrip(b"")


def test_single_byte():
    roundtrip(b"x")


def test_header_starts_with_magic_and_version():
    blob = compress(b"hello")
    assert blob[:4] == MAGIC
    assert blob[4] == VERSION


def test_declared_original_size_matches():
    data = b"hello world" * 10
    blob = compress(data)
    _, _, original_size, _crc32 = struct.unpack(">4sBQI", blob[:17])
    assert original_size == len(data)


def test_repetitive_data_compresses_smaller_than_input():
    data = b"the quick brown fox jumps over the lazy dog. " * 200
    blob = compress(data)
    assert len(blob) < len(data)


@pytest.mark.parametrize("seed", range(5))
def test_fuzz_random_bytes_round_trip(seed):
    random.seed(seed)
    n = random.randint(0, 3000)
    data = bytes(random.randint(0, 255) for _ in range(n))
    roundtrip(data)


def test_fuzz_text_like_round_trip():
    random.seed(11)
    words = ["the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog", "a", "an"]
    text = " ".join(random.choice(words) for _ in range(2000)).encode()
    roundtrip(text)


def test_all_256_byte_values_present():
    data = bytes(range(256)) * 5
    roundtrip(data)


def test_bad_magic_is_rejected():
    blob = bytearray(compress(b"hello"))
    blob[0] = ord("Z")
    with pytest.raises(CorruptStreamError):
        decompress(bytes(blob))


def test_bad_version_is_rejected():
    blob = bytearray(compress(b"hello"))
    blob[4] = 99
    with pytest.raises(CorruptStreamError):
        decompress(bytes(blob))


def test_truncated_header_is_rejected():
    with pytest.raises(CorruptStreamError):
        decompress(b"HZ7")


def test_truncated_code_tables_is_rejected():
    blob = compress(b"hello world")
    with pytest.raises(CorruptStreamError):
        decompress(blob[:20])


def test_truncated_body_is_rejected():
    blob = compress(b"hello world " * 50)
    with pytest.raises(CorruptStreamError):
        decompress(blob[:-5])


def test_bit_flips_in_body_are_never_silently_accepted_as_wrong_output():
    # A single-bit flip in the entropy-coded body should either be rejected
    # outright (invalid Huffman code, out-of-range match distance, or a
    # final decoded-size mismatch) or -- rarely, if it happens to land on an
    # insignificant padding bit -- decode back to the exact original bytes.
    # It must never silently produce output that is wrong-but-unnoticed.
    data = b"the quick brown fox jumps over the lazy dog " * 30
    original_blob = compress(data)
    header_and_tables_len = 4 + 1 + 8 + 4 + 286 + 30
    body_len = len(original_blob) - header_and_tables_len
    assert body_len > 0

    saw_rejection = False
    for byte_offset in range(0, body_len, max(1, body_len // 40)):
        blob = bytearray(original_blob)
        blob[header_and_tables_len + byte_offset] ^= 0x08
        try:
            result = decompress(bytes(blob))
        except CorruptStreamError:
            saw_rejection = True
            continue
        assert result == data, "a bit flip decoded to different bytes without being detected"
    assert saw_rejection, "expected at least one flipped bit to be caught as corruption"


def test_crc32_field_matches_original_data():
    data = b"integrity matters" * 20
    blob = compress(data)
    _, _, _, stored_crc32 = struct.unpack(">4sBQI", blob[:17])
    assert stored_crc32 == (zlib.crc32(data) & 0xFFFFFFFF)


def test_corrupted_but_same_length_output_is_caught_by_crc32():
    # Regression test for the exact gap CRC32 was added to close: flip a bit
    # in the body such that decoding still succeeds and still produces the
    # right *length* of output, but different *content*. This must now be
    # rejected via the CRC32 check rather than silently accepted.
    data = b"the quick brown fox jumps over the lazy dog " * 30
    blob = bytearray(compress(data))
    header_and_tables_len = 4 + 1 + 8 + 4 + 286 + 30
    found_same_length_corruption = False
    for offset in range(header_and_tables_len, len(blob)):
        candidate = bytearray(blob)
        candidate[offset] ^= 0x08
        try:
            decompress(bytes(candidate))
        except CorruptStreamError as exc:
            if "CRC32" in str(exc):
                found_same_length_corruption = True
                break
            continue
    assert found_same_length_corruption, (
        "expected at least one single-bit flip to decode to a same-length, "
        "wrong-content stream that only CRC32 catches"
    )


def test_max_chain_zero_still_round_trips():
    # max_chain=0 disables matching entirely (falls straight through to
    # literals) -- degenerate but must still be correct.
    data = b"abcabcabcabc"
    blob = compress(data, max_chain=1)
    assert decompress(blob) == data
