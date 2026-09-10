# huffman-lz77-compressor

A general-purpose file compressor built from scratch in Python, combining
**LZ77** sliding-window matching (finding repeated substrings and replacing
them with back-references) and **canonical Huffman coding** (giving common
symbols shorter bit patterns than rare ones) — the same two-stage design
DEFLATE (gzip/zip) is built on. No compression library is used anywhere in
the implementation; `zlib` is used for exactly one thing, a CRC-32 integrity
checksum (see "Container format" below), not for the compression itself.

```
$ hzc compress report.pdf
report.pdf: 1,204,801 -> 812,340 bytes (32.6% smaller, 2.1s) -> report.pdf.hz77

$ hzc decompress report.pdf.hz77 -o restored.pdf
report.pdf.hz77: 812,340 -> 1,204,801 bytes (0.4s) -> restored.pdf
```

## How it works

**1. LZ77 tokenization** (`lz77.py`) scans the input left to right. A hash
table keyed by every 3-byte prefix maps to the positions it has occurred at
before (a "hash chain" match finder, the same technique DEFLATE uses); at
each position the tokenizer walks a bounded number of candidate positions
looking for the longest match within a 32 KB window, then applies one step
of *lazy matching* — before committing to a match at position `i`, it also
checks whether position `i+1` has a strictly longer match, and if so emits a
literal at `i` instead so the better match at `i+1` wins. The output is a
sequence of literal bytes and `(length, distance)` matches (length 3-258,
distance 1-32768).

**2. Symbol/extra-bits encoding** (`tables.py`) turns each match's length
and distance into a small "code" — which gets Huffman-coded — plus a
handful of raw "extra bits" that select the exact value within that code's
range. This is the classic trick (also from DEFLATE) that keeps the Huffman
alphabet small (286 literal/length symbols, 30 distance symbols) instead of
needing a separate symbol for every one of the 258 possible lengths and
32768 possible distances.

**3. Canonical Huffman coding** (`huffman.py`) builds a standard Huffman
tree from symbol frequencies, but only keeps the *code lengths* it produces
— canonical Huffman codes are fully determined by their lengths (shortest
codes first, ties broken by symbol order), so the decoder only needs the
length table to reconstruct the exact same codes the encoder used. No tree
needs to be transmitted.

**4. Container format** (`format.py`) wraps it all up: a magic number,
format version, the original size, a CRC-32 checksum of the original data,
the two code-length tables (286 + 30 bytes), then the entropy-coded body,
terminated by an end-of-block symbol.

## Container format

```
+---------+---------+-------------------+-------------+-----------------------+------------------------+------------------+
| "HZ77"  | version | original_size u64 | crc32 u32   | litlen lengths (286B) | distance lengths (30B) | entropy-coded body
| 4 bytes | 1 byte  | 8 bytes, BE       | 4 bytes, BE | 1 byte/symbol, 0=unused| 1 byte/symbol, 0=unused| (see lz77.py/format.py)
+---------+---------+-------------------+-------------+-----------------------+------------------------+------------------+
```

Two intentional simplifications relative to real DEFLATE, both documented
where they're implemented:

* **Code lengths are stored as full bytes (0-255), not packed into 4 bits.**
  DEFLATE caps Huffman code lengths at 15 and needs a length-limiting pass
  (package-merge) for pathological frequency distributions. Reaching a code
  length anywhere near 255 with only 286 symbols would require a frequency
  ratio no real file produces (a Huffman code of length *L* needs total
  weight at least the *L*-th Fibonacci number), so this format skips length
  limiting entirely — simpler code, at the cost of a fixed ~330-byte header
  regardless of alphabet usage. (This is also why hzc is a poor choice for
  tiny files — see benchmarks below.)
* **A CRC-32 of the original data is stored and checked on decompress.**
  This was not part of the original design — it was added after a
  round-trip fuzz test that flipped individual bits across the compressed
  body and checked the *decoded content*, not just its length, caught a
  real gap: a single bit flip can decode to a different-but-equal-length
  sequence of Huffman symbols, which the original-size check alone can't
  detect. `zlib.crc32` computes the checksum (not the compression itself,
  which remains from-scratch); this mirrors gzip's own CRC-32 trailer.

## Tech stack

Python 3.9+, standard library only (`zlib` for the CRC-32 checksum
described above — no compression library is used). Dev/test: `pytest`,
`pyflakes`.

## Project layout

```
src/huffman_lz77/
    bitio.py     BitWriter/BitReader — MSB-first bit-level packing
    tables.py    length/distance code tables (base value + extra bits)
    huffman.py   canonical Huffman: build lengths, assign codes, encode/decode
    lz77.py      sliding-window tokenizer/detokenizer with lazy matching
    format.py    container format: header + code tables + entropy-coded body
    cli.py       `hzc compress` / `hzc decompress`
tests/           77 tests: bit-level fuzzing, Kraft-inequality checks,
                 canonical-code round-trips, LZ77 round-trips (including
                 overlapping matches and window-boundary edge cases),
                 full-format round-trips, corruption/CRC handling, CLI
                 subprocess tests
benchmarks/      fixture generator + a gzip comparison harness
```

## How to run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

hzc compress path/to/file            # -> path/to/file.hz77
hzc decompress path/to/file.hz77     # -> path/to/file
hzc compress path/to/file -o out.hz77 --max-chain 512   # slower, better ratio
hzc --help

pytest                                # run the test suite
pyflakes src tests                    # lint

python benchmarks/generate_fixtures.py   # writes benchmarks/fixtures/ (gitignored)
python benchmarks/compare_gzip.py
```

## Benchmark: hzc vs. gzip -9

Measured on this run's fixtures (`benchmarks/generate_fixtures.py`):

| file                  | original  | hzc     | gzip -9 | hzc / gzip |
|-----------------------|-----------|---------|---------|------------|
| english_repeated.txt  | 796,000 B | 3,548 B | 3,272 B | 1.08x      |
| source_code.py        | 337,120 B | 90,729 B| 91,380 B| 0.99x      |
| dna_like.txt          | 200,000 B | 59,092 B| 58,291 B| 1.01x      |
| random_bytes.bin      | 200,000 B | 200,466 B| 200,083 B| 1.00x    |

hzc lands within a few percent of gzip's ratio across highly-compressible,
moderately-compressible, and incompressible inputs — including edging it
out on the source-code fixture — which is a reasonable outcome for lazy
matching (vs. DEFLATE's more exhaustive optimal-ish parsing) plus a Huffman
stage built the same way DEFLATE's is. hzc is pure Python, so it is not
trying to compete with zlib's C implementation on speed (roughly two orders
of magnitude slower); the benchmark harness reports compress/decompress
wall-clock time for both so this tradeoff is visible, not hidden.

## Current status

**Working and tested (v1):**
- LZ77 tokenizer/detokenizer with hash-chain matching and lazy matching,
  including overlapping matches (e.g. long runs of one repeated byte) and
  window-boundary edge cases.
- Canonical Huffman coding: tree-based code-length construction, canonical
  code assignment, bit-level encode/decode, verified against a hand-derived
  textbook example and fuzzed against the Kraft inequality.
- Full container format with CRC-32 integrity checking.
- `hzc` CLI (`compress`/`decompress`, custom output paths, verbose/quiet
  modes, refuses to overwrite input, reports clear errors on corrupt input).
- 77 tests (unit + fuzz + CLI subprocess tests), all passing; `pyflakes`
  clean; benchmarked against gzip on 4 fixture types.

**Known limitations / not done:**
- Pure-Python performance: fine for CLI use on files up to a few MB, not
  competitive with a C implementation for large files (see benchmark
  timings above).
- No streaming API — `compress`/`decompress` operate on an in-memory
  `bytes` object, so peak memory is roughly proportional to input size.
- No archive/multi-file support (single file in, single file out, like
  `gzip` rather than `zip`/`tar`).
- No optimal parsing (a full shortest-path LZ77 parse can beat greedy +
  one-step lazy matching by a few more percent, at significant extra
  implementation and runtime cost) — left as a possible future improvement.

## Two real bugs this project's own test suite caught during development

- **Kraft-inequality test had the wrong expectation, not the code.** A fuzz
  test asserted `sum(2**-length) == 1.0` for every random frequency
  distribution. It failed on inputs with exactly one used symbol. Tracing
  it by hand: Kraft's inequality only requires `sum <= 1`, with equality
  for a *complete* code (every internal tree node has two children).
  Standard Huffman construction always produces a complete tree once there
  are >= 2 used symbols, but with only one symbol there's nothing to pair it
  with — it gets a 1-bit code with an unused sibling leaf, so the sum is
  0.5, not 1.0. The single-symbol code is still perfectly decodable; the
  test's blanket assumption was the bug, not `build_code_lengths`.
- **No integrity checksum meant some single-bit corruptions were silently
  accepted.** A fuzz test that flipped individual bits throughout the
  compressed body and compared *decoded content* (not just decoded length)
  against the original found cases where a flipped bit decoded to a
  different-but-same-length byte sequence, with no error raised. The fix
  was a real design gap, not a test bug: a CRC-32 of the original data was
  added to the header and is checked on every decompress, closing the gap
  (see "Container format" above).
