import random

import pytest

from huffman_lz77.lz77 import Literal, Match, detokenize, tokenize
from huffman_lz77.tables import MAX_MATCH, MAX_WINDOW, MIN_MATCH


def roundtrip(data: bytes):
    tokens = tokenize(data)
    assert detokenize(tokens) == data
    return tokens


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"a",
        b"ab",
        b"aaa",
        b"abcabcabcabcabcabc",
        b"the quick brown fox jumps over the lazy dog. the quick brown fox.",
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        bytes(range(256)),
        bytes(range(256)) * 3,
    ],
)
def test_round_trip_various_inputs(data):
    roundtrip(data)


def test_no_matches_for_all_unique_bytes():
    data = bytes(range(256))
    tokens = tokenize(data)
    assert all(isinstance(t, Literal) for t in tokens)
    assert len(tokens) == 256


def test_repeated_pattern_produces_matches():
    data = b"abcdefgh" * 20
    tokens = tokenize(data)
    assert any(isinstance(t, Match) for t in tokens)
    roundtrip(data)


def test_long_run_of_single_byte_uses_overlapping_matches():
    data = b"z" * 1000
    tokens = tokenize(data)
    matches = [t for t in tokens if isinstance(t, Match)]
    assert matches, "expected at least one match in a long repeated run"
    assert any(m.distance < m.length for m in matches), "expected an overlapping match"
    assert detokenize(tokens) == data


def test_match_lengths_and_distances_are_in_range():
    random.seed(4)
    data = bytes(random.choice(b"abcd") for _ in range(5000))
    tokens = tokenize(data)
    for t in tokens:
        if isinstance(t, Match):
            assert MIN_MATCH <= t.length <= MAX_MATCH
            assert 1 <= t.distance <= MAX_WINDOW


def test_detokenize_rejects_distance_beyond_output():
    with pytest.raises(ValueError):
        detokenize([Literal(ord("a")), Match(length=3, distance=5)])


def test_detokenize_rejects_zero_distance():
    with pytest.raises(ValueError):
        detokenize([Literal(ord("a")), Match(length=3, distance=0)])


def test_fuzz_random_binary_round_trip():
    random.seed(5)
    for _ in range(10):
        n = random.randint(0, 4000)
        data = bytes(random.randint(0, 255) for _ in range(n))
        roundtrip(data)


def test_fuzz_low_entropy_round_trip():
    # Small alphabet -> lots of matches, exercises the hash-chain search and
    # lazy-matching lookahead heavily.
    random.seed(6)
    for _ in range(10):
        n = random.randint(0, 4000)
        data = bytes(random.choice(b"ab") for _ in range(n))
        roundtrip(data)


def test_max_chain_parameter_still_round_trips():
    data = (b"mississippi river " * 50) + bytes(range(200))
    for max_chain in (1, 4, 512):
        tokens = tokenize(data, max_chain=max_chain)
        assert detokenize(tokens) == data


def test_window_boundary_no_match_beyond_max_window():
    # Construct input where a repeat occurs just outside MAX_WINDOW so it
    # must be re-emitted as literals rather than an out-of-range match.
    prefix = b"UNIQUEPATTERN123"
    filler = bytes((i * 37) % 256 for i in range(MAX_WINDOW + 100))
    data = prefix + filler + prefix
    tokens = tokenize(data)
    assert detokenize(tokens) == data
    for t in tokens:
        if isinstance(t, Match):
            assert t.distance <= MAX_WINDOW
