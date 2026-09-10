import random

import pytest

from huffman_lz77.bitio import BitReader, BitWriter


def test_empty_writer_produces_empty_bytes():
    w = BitWriter()
    assert w.getvalue() == b""
    assert len(w) == 0


def test_single_bit():
    w = BitWriter()
    w.write_bits(1, 1)
    assert w.getvalue() == bytes([0b10000000])


def test_msb_first_ordering():
    w = BitWriter()
    w.write_bits(0b101, 3)
    # 3 bits "101" then 5 zero-padding bits -> 0b10100000
    assert w.getvalue() == bytes([0b10100000])


def test_exact_byte_boundary():
    w = BitWriter()
    w.write_bits(0xAB, 8)
    assert w.getvalue() == bytes([0xAB])
    assert len(w) == 8


def test_spans_multiple_bytes():
    w = BitWriter()
    w.write_bits(0b1, 1)
    w.write_bits(0xFF, 8)
    w.write_bits(0b1, 1)
    data = w.getvalue()
    r = BitReader(data)
    assert r.read_bits(1) == 0b1
    assert r.read_bits(8) == 0xFF
    assert r.read_bits(1) == 0b1


def test_write_bits_rejects_value_too_large():
    w = BitWriter()
    with pytest.raises(ValueError):
        w.write_bits(4, 2)  # 4 needs 3 bits, not 2


def test_write_bits_zero_width_is_noop():
    w = BitWriter()
    w.write_bits(0, 0)
    assert len(w) == 0


def test_align_pads_with_zero_bits():
    w = BitWriter()
    w.write_bits(0b111, 3)
    w.align()
    assert len(w) == 8
    assert w.getvalue() == bytes([0b11100000])


def test_write_bytes_aligned_after_partial_byte():
    w = BitWriter()
    w.write_bits(0b1, 1)
    w.write_bytes_aligned(b"\x01\x02")
    data = w.getvalue()
    assert data == bytes([0b10000000, 0x01, 0x02])


def test_reader_eof_raises():
    r = BitReader(b"\xff")
    r.read_bits(8)
    with pytest.raises(EOFError):
        r.read_bits(1)


def test_reader_align_and_read_bytes_aligned():
    w = BitWriter()
    w.write_bits(0b11, 2)
    w.write_bytes_aligned(b"hello")
    r = BitReader(w.getvalue())
    assert r.read_bits(2) == 0b11
    assert r.read_bytes_aligned(5) == b"hello"


def test_read_bytes_aligned_not_enough_data_raises():
    r = BitReader(b"\x00\x00")
    with pytest.raises(EOFError):
        r.read_bytes_aligned(5)


def test_fuzz_round_trip():
    random.seed(12345)
    w = BitWriter()
    plan = []
    for _ in range(5000):
        nbits = random.randint(0, 20)
        value = random.randint(0, (1 << nbits) - 1) if nbits else 0
        plan.append((value, nbits))
        w.write_bits(value, nbits)
    r = BitReader(w.getvalue())
    for value, nbits in plan:
        assert r.read_bits(nbits) == value


def test_getvalue_is_non_destructive():
    w = BitWriter()
    w.write_bits(0b101, 3)
    # Calling getvalue() twice with no writes in between must be idempotent...
    assert w.getvalue() == w.getvalue()
    # ...and writing more afterward must continue from bit 3, not from a
    # flushed/reset state (which would misalign every subsequent bit).
    w.write_bits(0b1, 1)
    assert len(w) == 4
    w.write_bits(0b0000, 4)
    assert w.getvalue() == bytes([0b10110000])
