"""LZ77 sliding-window tokenizer.

Scans the input left to right, hashing every 3-byte prefix into a chain of
prior positions with the same prefix (a standard "hash chain" match finder,
the same technique DEFLATE uses). At each position it walks a bounded number
of candidate positions (most recent first) looking for the longest match
within the window, then applies one step of *lazy matching*: before
committing to a match at position `i`, it also checks whether position `i+1`
has a strictly longer match — if so, it emits a literal at `i` and lets the
better match at `i+1` win. This is the single biggest compression-ratio win
available without a full optimal-parse search, at the cost of one extra
match lookup per position.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from .tables import MAX_MATCH, MAX_WINDOW, MIN_MATCH

# How many candidate positions to examine per hash bucket before giving up
# and taking the best match found so far. Bounds worst-case time on inputs
# with long runs of a repeated 3-byte prefix (e.g. "aaaaaaa...").
DEFAULT_MAX_CHAIN = 128


@dataclass(frozen=True)
class Literal:
    byte: int


@dataclass(frozen=True)
class Match:
    length: int
    distance: int


Token = Union[Literal, Match]


class _HashChains:
    """Maps a 3-byte prefix to the positions it occurred at, most recent
    last, periodically trimmed so lookups stay bounded even on inputs with
    huge repeated runs.
    """

    def __init__(self, max_chain: int) -> None:
        self._max_chain = max_chain
        self._table: Dict[bytes, List[int]] = {}

    def candidates(self, key: bytes) -> List[int]:
        return self._table.get(key, [])

    def insert(self, key: bytes, pos: int) -> None:
        bucket = self._table.setdefault(key, [])
        bucket.append(pos)
        if len(bucket) > 4 * self._max_chain:
            cutoff = pos - MAX_WINDOW
            trimmed = [p for p in bucket if p >= cutoff]
            self._table[key] = trimmed[-2 * self._max_chain :]


def _find_match(
    data: bytes, pos: int, chains: _HashChains, n: int
) -> Optional[Tuple[int, int]]:
    if pos + MIN_MATCH > n:
        return None
    key = data[pos : pos + 3]
    candidates = chains.candidates(key)
    if not candidates:
        return None
    limit = min(MAX_MATCH, n - pos)
    best_len = 0
    best_dist = 0
    tried = 0
    for cand in reversed(candidates):  # most recent (smallest distance) first
        dist = pos - cand
        if dist > MAX_WINDOW:
            # Candidates are visited in decreasing-position (increasing
            # distance) order, so every remaining one is even farther away.
            break
        tried += 1
        length = 0
        while length < limit and data[cand + length] == data[pos + length]:
            length += 1
        if length > best_len:
            best_len, best_dist = length, dist
            if length >= limit:
                break
        if tried >= chains._max_chain:
            break
    if best_len >= MIN_MATCH:
        return best_len, best_dist
    return None


def tokenize(data: bytes, max_chain: int = DEFAULT_MAX_CHAIN) -> List[Token]:
    n = len(data)
    chains = _HashChains(max_chain)
    tokens: List[Token] = []
    i = 0
    while i < n:
        match = _find_match(data, i, chains, n)
        if i + 3 <= n:
            chains.insert(data[i : i + 3], i)
        if match is not None:
            length, dist = match
            # Lazy matching: is there a strictly better match starting one
            # byte later? If so, prefer emitting a literal now.
            if i + 1 < n:
                if i + 1 + 3 <= n:
                    # Insert i+1's hash entry lazily too so the lookahead
                    # match search sees it if it helps (mirrors zlib).
                    pass
                next_match = _find_match(data, i + 1, chains, n)
            else:
                next_match = None
            if next_match is not None and next_match[0] > length:
                tokens.append(Literal(data[i]))
                i += 1
                continue
            tokens.append(Match(length, dist))
            for p in range(i + 1, i + length):
                if p + 3 <= n:
                    chains.insert(data[p : p + 3], p)
            i += length
        else:
            tokens.append(Literal(data[i]))
            i += 1
    return tokens


def detokenize(tokens: List[Token]) -> bytes:
    out = bytearray()
    for tok in tokens:
        if isinstance(tok, Literal):
            out.append(tok.byte)
        elif isinstance(tok, Match):
            length, distance = tok.length, tok.distance
            if distance <= 0 or distance > len(out):
                raise ValueError(
                    f"invalid match: distance {distance} exceeds {len(out)} bytes decoded so far"
                )
            start = len(out) - distance
            # Byte-by-byte so overlapping matches (distance < length, e.g. a
            # run of one repeated byte encoded as a single long match) work:
            # each appended byte becomes readable for the *next* iteration.
            for k in range(length):
                out.append(out[start + k])
        else:
            raise TypeError(f"unknown token type: {tok!r}")
    return bytes(out)
