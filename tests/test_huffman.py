import random

import pytest

from huffman_lz77.bitio import BitReader, BitWriter
from huffman_lz77.huffman import (
    CanonicalCode,
    assign_canonical_codes,
    build_code_lengths,
    build_decode_tree,
)


def kraft_sum(lengths):
    return sum(2.0 ** (-l) for l in lengths if l > 0)


def test_classic_textbook_example():
    # The standard CLRS-style worked example: symbols with frequencies
    # 5, 9, 12, 13, 16, 45 (symbol 5 is by far the most common and should
    # get the shortest code, length 1).
    freqs = [5, 9, 12, 13, 16, 45]
    lengths = build_code_lengths(freqs)
    assert lengths[5] == 1  # most frequent symbol gets the shortest code
    assert lengths[5] < lengths[0]  # least frequent gets a longer code
    assert kraft_sum(lengths) == pytest.approx(1.0)


def test_single_used_symbol_gets_length_one():
    freqs = [0, 0, 7, 0]
    lengths = build_code_lengths(freqs)
    assert lengths == [0, 0, 1, 0]


def test_all_zero_frequencies_gives_all_zero_lengths():
    lengths = build_code_lengths([0, 0, 0])
    assert lengths == [0, 0, 0]


def test_two_symbols_get_length_one_each():
    lengths = build_code_lengths([3, 7])
    assert sorted(lengths) == [1, 1]
    assert kraft_sum(lengths) == pytest.approx(1.0)


def test_kraft_inequality_holds_for_random_distributions():
    # Kraft's inequality (sum of 2**-length over used symbols <= 1) is a
    # necessary condition for *any* valid prefix code. Equality holds only
    # for a "complete" code, i.e. one whose tree has no wasted leaf. Standard
    # Huffman construction always yields a complete tree when there are >= 2
    # used symbols (every internal node gets exactly two children) -- but
    # with exactly one used symbol there is nothing to pair it with, so it
    # gets a 1-bit code with an unused sibling leaf, and the sum is 0.5, not
    # 1.0. (First draft of this test asserted ==1.0 unconditionally and
    # failed on n=1 inputs -- tracing it by hand confirmed the *test*, not
    # build_code_lengths, had the wrong expectation.)
    random.seed(7)
    for _ in range(20):
        n = random.randint(1, 50)
        freqs = [random.randint(0, 100) for _ in range(n)]
        if sum(freqs) == 0:
            freqs[0] = 1
        lengths = build_code_lengths(freqs)
        used = sum(1 for l in lengths if l > 0)
        if used >= 2:
            assert kraft_sum(lengths) == pytest.approx(1.0)
        elif used == 1:
            assert kraft_sum(lengths) == pytest.approx(0.5)
        else:
            assert kraft_sum(lengths) == 0.0


def test_canonical_codes_are_prefix_free():
    freqs = [5, 9, 12, 13, 16, 45]
    lengths = build_code_lengths(freqs)
    table = assign_canonical_codes(lengths)
    # No code should be a bit-prefix of another.
    entries = list(table.values())
    for i, (code_a, len_a) in enumerate(entries):
        bits_a = format(code_a, f"0{len_a}b")
        for j, (code_b, len_b) in enumerate(entries):
            if i == j:
                continue
            bits_b = format(code_b, f"0{len_b}b")
            shorter, longer = (bits_a, bits_b) if len_a <= len_b else (bits_b, bits_a)
            assert not longer.startswith(shorter), "codes are not prefix-free"


def test_canonical_codes_increase_in_symbol_order_at_same_length():
    lengths = [3, 3, 3, 3, 3]
    table = assign_canonical_codes(lengths)
    codes_in_symbol_order = [table[s][0] for s in range(5)]
    assert codes_in_symbol_order == sorted(codes_in_symbol_order)


def test_decode_tree_rejects_non_prefix_free_lengths_defensively():
    # Two symbols both assigned the same explicit code would not be
    # prefix-free; build_decode_tree should refuse to silently overwrite.
    bad_table = {0: (0b0, 1), 1: (0b0, 1)}
    with pytest.raises(ValueError):
        build_decode_tree(bad_table)


def test_canonical_code_encode_decode_round_trip():
    freqs = [5, 9, 12, 13, 16, 45]
    code = CanonicalCode.from_frequencies(freqs)
    symbols = [5, 5, 5, 0, 1, 2, 3, 4, 5, 5]
    w = BitWriter()
    for s in symbols:
        code.encode_symbol(w, s)
    r = BitReader(w.getvalue())
    decoded = [code.decode_symbol(r) for _ in symbols]
    assert decoded == symbols


def test_encode_unused_symbol_raises():
    code = CanonicalCode.from_frequencies([0, 5, 0])
    w = BitWriter()
    with pytest.raises(ValueError):
        code.encode_symbol(w, 0)


def test_from_lengths_reconstructs_identical_code_to_from_frequencies():
    freqs = [5, 9, 12, 13, 16, 45]
    original = CanonicalCode.from_frequencies(freqs)
    rebuilt = CanonicalCode.from_lengths(original.lengths)
    assert original.encode_table == rebuilt.encode_table


def test_fuzz_round_trip_large_alphabet():
    random.seed(99)
    freqs = [random.randint(0, 40) for _ in range(286)]
    if sum(freqs) == 0:
        freqs[0] = 1
    code = CanonicalCode.from_frequencies(freqs)
    used_symbols = [s for s, f in enumerate(freqs) if f > 0]
    stream = [random.choice(used_symbols) for _ in range(3000)]
    w = BitWriter()
    for s in stream:
        code.encode_symbol(w, s)
    r = BitReader(w.getvalue())
    for expected in stream:
        assert code.decode_symbol(r) == expected


def test_decode_empty_code_table_raises():
    code = CanonicalCode.from_frequencies([0, 0, 0])
    r = BitReader(b"\x00")
    with pytest.raises(ValueError):
        code.decode_symbol(r)
