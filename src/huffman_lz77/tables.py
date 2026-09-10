"""Length/distance code tables shared by the LZ77 tokenizer and the container format.

LZ77 emits (length, distance) matches with length in [MIN_MATCH, MAX_MATCH] and
distance in [1, MAX_WINDOW]. Encoding every possible length/distance value as its
own Huffman symbol would blow up the alphabet, so — following the classic DEFLATE
approach — each match is instead represented as a small "code" (which IS Huffman
coded) plus a handful of "extra bits" (written raw, not entropy coded) that select
the exact value within the code's range.

Both tables are (base_value, extra_bits) pairs, sorted so code index i covers
values [base_value[i], base_value[i] + 2**extra_bits[i] - 1], contiguous and with
no gaps, up to MAX_MATCH / MAX_WINDOW respectively.
"""
from __future__ import annotations

MIN_MATCH = 3
MAX_MATCH = 258
MAX_WINDOW = 32768

# --- Length codes -----------------------------------------------------------
# 29 codes covering lengths 3..258. Symbol id for length code i (0-indexed) is
# LITLEN_LENGTH_BASE_SYMBOL + i in the literal/length alphabet.
LITLEN_LENGTH_BASE_SYMBOL = 257
END_OF_BLOCK_SYMBOL = 256
LITLEN_ALPHABET_SIZE = 286  # 0-255 literals, 256 EOB, 257-285 length codes (29)


def _build_length_table():
    # 29 codes covering lengths 3..258, built from an explicit (extra_bits)
    # sequence: eight exact codes (3-10), then groups of four codes whose
    # extra-bit width grows 1,2,3,4, and a final exact code pinned to 258
    # (rather than letting the last group run 2**5=32 wide, which would
    # overshoot 258 by one — this is the one place deflate's real table
    # special-cases the top of the range, and we match it deliberately).
    extra_bits_sequence = (
        [0] * 8
        + [1] * 4
        + [2] * 4
        + [3] * 4
        + [4] * 4
        + [5] * 4
    )
    assert len(extra_bits_sequence) == 28
    bases = []
    v = MIN_MATCH
    for eb in extra_bits_sequence:
        bases.append(v)
        v += 1 << eb
    # After the loop, v == 131 + 128 == 259 — one past where we want the
    # final code to land, because the last group of four 5-extra-bit codes
    # covers 131..258 in only 4*32=128 slots, i.e. exactly 131..258. Good —
    # so v should already be 259. The 29th code is the exact-length sentinel.
    assert v == MAX_MATCH + 1, v
    bases.append(MAX_MATCH)
    extra_bits_sequence.append(0)
    extras = extra_bits_sequence
    assert len(bases) == 29
    assert bases[-1] == MAX_MATCH and extras[-1] == 0
    for i in range(1, len(bases) - 1):
        assert bases[i] == bases[i - 1] + (1 << extras[i - 1]), "length table has a gap"
    # The second-to-last code (extra=5, base 227) nominally covers 227-258
    # (32 values) but the sentinel code claims 258 for itself, so its
    # *usable* range is 227-257 (31 values) — enforced in length_to_code by
    # checking the sentinel (exact match on 258) before falling through.
    return bases, extras


LENGTH_BASE, LENGTH_EXTRA_BITS = _build_length_table()


def length_to_code(length: int) -> tuple[int, int, int]:
    """Return (code_index, extra_bits, extra_value) for a match length."""
    if not (MIN_MATCH <= length <= MAX_MATCH):
        raise ValueError(f"length {length} out of range [{MIN_MATCH}, {MAX_MATCH}]")
    # Linear scan is fine: only 29 codes.
    for i in range(len(LENGTH_BASE) - 1, -1, -1):
        if length >= LENGTH_BASE[i]:
            return i, LENGTH_EXTRA_BITS[i], length - LENGTH_BASE[i]
    raise AssertionError("unreachable")


def code_to_length(code_index: int, extra_value: int) -> int:
    return LENGTH_BASE[code_index] + extra_value


# --- Distance codes ----------------------------------------------------------
# 30 codes covering distances 1..32768.
DISTANCE_ALPHABET_SIZE = 30


def _build_distance_table():
    # Codes come in pairs sharing an extra-bit width, and that width grows by
    # 1 every 2 codes (after 4 exact codes to start): this is the standard
    # deflate distance extra-bit sequence, which reaches exactly 32768 with
    # 30 codes.
    extra_bits_sequence = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7,
                            8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]
    assert len(extra_bits_sequence) == 30
    bases = []
    v = 1
    for eb in extra_bits_sequence:
        bases.append(v)
        v += 1 << eb
    assert bases[-1] + (1 << extra_bits_sequence[-1]) - 1 == MAX_WINDOW, (
        bases[-1], extra_bits_sequence[-1]
    )
    return bases, extra_bits_sequence


DISTANCE_BASE, DISTANCE_EXTRA_BITS = _build_distance_table()


def distance_to_code(distance: int) -> tuple[int, int, int]:
    """Return (code_index, extra_bits, extra_value) for a match distance."""
    if not (1 <= distance <= MAX_WINDOW):
        raise ValueError(f"distance {distance} out of range [1, {MAX_WINDOW}]")
    for i in range(len(DISTANCE_BASE) - 1, -1, -1):
        if distance >= DISTANCE_BASE[i]:
            return i, DISTANCE_EXTRA_BITS[i], distance - DISTANCE_BASE[i]
    raise AssertionError("unreachable")


def code_to_distance(code_index: int, extra_value: int) -> int:
    return DISTANCE_BASE[code_index] + extra_value
