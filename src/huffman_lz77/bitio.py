"""Bit-level I/O helpers.

Bits are packed MSB-first within each byte: the first bit written becomes the
top bit (0x80) of the first output byte. BitWriter and BitReader are exact
inverses of each other for both raw fixed-width integers and (code, length)
Huffman codepoints, which are also represented as plain ints with an explicit
bit-length (so a codepoint like 0b011 of length 3 is written as three bits,
MSB first: 0, 1, 1).
"""
from __future__ import annotations


class BitWriter:
    def __init__(self) -> None:
        self._bytes = bytearray()
        self._cur = 0  # bits accumulated for the in-progress byte
        self._nbits = 0  # how many bits are in `_cur` so far (0-7)

    def write_bits(self, value: int, nbits: int) -> None:
        """Write the `nbits` low bits of `value`, MSB first."""
        if nbits < 0:
            raise ValueError("nbits must be >= 0")
        if nbits and (value < 0 or value >= (1 << nbits)):
            raise ValueError(f"value {value} does not fit in {nbits} bits")
        for i in range(nbits - 1, -1, -1):
            bit = (value >> i) & 1
            self._cur = (self._cur << 1) | bit
            self._nbits += 1
            if self._nbits == 8:
                self._bytes.append(self._cur)
                self._cur = 0
                self._nbits = 0

    def write_bytes_aligned(self, data: bytes) -> None:
        """Pad to a byte boundary with zero bits, then append raw bytes."""
        self.align()
        self._bytes.extend(data)

    def align(self) -> None:
        if self._nbits:
            self._cur <<= 8 - self._nbits
            self._bytes.append(self._cur)
            self._cur = 0
            self._nbits = 0

    def getvalue(self) -> bytes:
        # Non-destructive: flush a *copy* of any partial byte, padded with
        # zero bits, without disturbing the writer's own state.
        if self._nbits == 0:
            return bytes(self._bytes)
        pad = self._cur << (8 - self._nbits)
        return bytes(self._bytes) + bytes([pad])

    def __len__(self) -> int:
        """Total bits written so far."""
        return len(self._bytes) * 8 + self._nbits


class BitReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._byte_pos = 0
        self._bit_pos = 0  # 0-7, next bit to read within data[_byte_pos]

    def read_bits(self, nbits: int) -> int:
        value = 0
        for _ in range(nbits):
            value = (value << 1) | self._read_bit()
        return value

    def _read_bit(self) -> int:
        if self._byte_pos >= len(self._data):
            raise EOFError("BitReader ran out of data")
        byte = self._data[self._byte_pos]
        bit = (byte >> (7 - self._bit_pos)) & 1
        self._bit_pos += 1
        if self._bit_pos == 8:
            self._bit_pos = 0
            self._byte_pos += 1
        return bit

    def align(self) -> None:
        if self._bit_pos:
            self._bit_pos = 0
            self._byte_pos += 1

    def read_bytes_aligned(self, n: int) -> bytes:
        self.align()
        chunk = self._data[self._byte_pos : self._byte_pos + n]
        if len(chunk) != n:
            raise EOFError("not enough bytes remaining")
        self._byte_pos += n
        return chunk

    @property
    def bits_consumed(self) -> int:
        return self._byte_pos * 8 + self._bit_pos
