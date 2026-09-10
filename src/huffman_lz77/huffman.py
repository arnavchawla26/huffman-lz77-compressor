"""Canonical Huffman coding.

A canonical Huffman code is fully determined by the *code length* assigned to
each symbol (not by the shape of the tree that produced those lengths): given
the lengths, codes are assigned in increasing (length, symbol) order, which
means a decoder only needs to know the lengths to reconstruct the exact same
codes the encoder used — no tree needs to be transmitted. This module builds
code lengths from symbol frequencies via a standard Huffman-tree construction,
then derives canonical codes from those lengths (RFC 1951 section 3.2.2's
algorithm), and provides bit-level encode/decode against a BitWriter/BitReader.

Design choice: unlike DEFLATE, which packs code lengths into 4 bits (capping
them at 15 and requiring a length-limiting pass such as package-merge for
pathological inputs), this implementation stores each code length as a plain
byte (0-255) in the container header. For any alphabet this small (at most
286 symbols here), reaching a code length anywhere near 255 would require a
symbol-frequency ratio no real file will ever produce (Huffman code length L
requires total weight at least the L-th Fibonacci number), so length-limiting
is unnecessary in practice — and skipping it keeps the tree-building code
simple and easy to verify by hand.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from .bitio import BitReader, BitWriter


def build_code_lengths(freqs: list[int]) -> list[int]:
    """Compute a Huffman code length per symbol from a frequency table.

    `freqs[i]` is the count of symbol `i`; symbols with freq 0 get length 0
    (unused). Ties in the priority queue are broken by insertion order, which
    makes the resulting tree shape (and hence the length assignment)
    deterministic for a given input.
    """
    n = len(freqs)
    used = [i for i, f in enumerate(freqs) if f > 0]
    lengths = [0] * n
    if not used:
        return lengths
    if len(used) == 1:
        # A single symbol still needs a real code (length >= 1) so the
        # bitstream carries something to decode; canonical assignment below
        # will give it code "0".
        lengths[used[0]] = 1
        return lengths

    heap: list[tuple[int, int, int]] = []
    counter = 0
    children: dict[int, tuple[int, int]] = {}
    for i in used:
        heapq.heappush(heap, (freqs[i], counter, i))
        counter += 1
    next_id = n
    while len(heap) > 1:
        f1, _, a = heapq.heappop(heap)
        f2, _, b = heapq.heappop(heap)
        children[next_id] = (a, b)
        heapq.heappush(heap, (f1 + f2, counter, next_id))
        counter += 1
        next_id += 1
    _, _, root = heap[0]

    stack: list[tuple[int, int]] = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if node in children:
            a, b = children[node]
            stack.append((a, depth + 1))
            stack.append((b, depth + 1))
        else:
            # A lone root with no children at all (shouldn't happen once
            # len(used) > 1, since the loop always merges down to one node
            # with two children) — guard anyway for safety.
            lengths[node] = max(depth, 1)
    return lengths


def assign_canonical_codes(lengths: list[int]) -> dict[int, tuple[int, int]]:
    """Given code lengths, return {symbol: (code, length)} using the
    canonical assignment: shortest codes first, ties broken by ascending
    symbol id, each code one more than the previous at that length.
    """
    if not lengths or max(lengths) == 0:
        return {}
    max_len = max(lengths)
    bl_count = [0] * (max_len + 1)
    for length in lengths:
        if length > 0:
            bl_count[length] += 1
    code = 0
    next_code = [0] * (max_len + 1)
    for bits in range(1, max_len + 1):
        code = (code + bl_count[bits - 1]) << 1
        next_code[bits] = code
    table: dict[int, tuple[int, int]] = {}
    for symbol, length in enumerate(lengths):
        if length > 0:
            table[symbol] = (next_code[length], length)
            next_code[length] += 1
    return table


def build_decode_tree(encode_table: dict[int, tuple[int, int]]) -> dict:
    """Build a nested-dict bit trie: tree[0]/tree[1] descend by bit (MSB
    first), and a leaf is marked by the special key "symbol".
    """
    root: dict = {}
    for symbol, (code, length) in encode_table.items():
        node = root
        for i in range(length - 1, -1, -1):
            bit = (code >> i) & 1
            node = node.setdefault(bit, {})
        if "symbol" in node:
            raise ValueError("canonical code table is not prefix-free (bug)")
        node["symbol"] = symbol
    return root


@dataclass
class CanonicalCode:
    """A complete canonical Huffman code for a fixed-size alphabet."""

    lengths: list[int]
    encode_table: dict[int, tuple[int, int]] = field(repr=False)
    decode_tree: dict = field(repr=False)

    @classmethod
    def from_frequencies(cls, freqs: list[int]) -> "CanonicalCode":
        lengths = build_code_lengths(freqs)
        return cls.from_lengths(lengths)

    @classmethod
    def from_lengths(cls, lengths: list[int]) -> "CanonicalCode":
        encode_table = assign_canonical_codes(lengths)
        decode_tree = build_decode_tree(encode_table)
        return cls(lengths=list(lengths), encode_table=encode_table, decode_tree=decode_tree)

    @property
    def alphabet_size(self) -> int:
        return len(self.lengths)

    def encode_symbol(self, writer: BitWriter, symbol: int) -> None:
        try:
            code, length = self.encode_table[symbol]
        except KeyError as exc:
            raise ValueError(f"symbol {symbol} has no assigned code (zero frequency)") from exc
        writer.write_bits(code, length)

    def decode_symbol(self, reader: BitReader) -> int:
        node = self.decode_tree
        if not node:
            raise ValueError("cannot decode from an empty code table")
        while "symbol" not in node:
            bit = reader.read_bits(1)
            if bit not in node:
                raise ValueError("invalid Huffman bitstream: no matching code")
            node = node[bit]
        return node["symbol"]
