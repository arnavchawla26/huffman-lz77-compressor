"""Generates benchmark fixture files without committing large binary blobs to
the repo. Run this before compare_gzip.py.

    python benchmarks/generate_fixtures.py

Produces (under benchmarks/fixtures/, gitignored):
    english_repeated.txt   -- a paragraph repeated many times (highly compressible)
    random_bytes.bin       -- uniform random bytes (incompressible, worst case)
    source_code.py         -- this repo's own Python source, concatenated
    dna_like.txt           -- a long string over a 4-letter alphabet (mid-entropy)
"""
from __future__ import annotations

import pathlib
import random

HERE = pathlib.Path(__file__).parent
FIXTURES_DIR = HERE / "fixtures"

PARAGRAPH = (
    "The quick brown fox jumps over the lazy dog. Pack my box with five dozen "
    "liquor jugs. How vexingly quick daft zebras jump! The five boxing wizards "
    "jump quickly. Sphinx of black quartz, judge my vow. "
)


def make_english_repeated(path: pathlib.Path, repeats: int = 4000) -> None:
    path.write_text(PARAGRAPH * repeats)


def make_random_bytes(path: pathlib.Path, size: int = 200_000, seed: int = 42) -> None:
    rng = random.Random(seed)
    path.write_bytes(bytes(rng.randrange(256) for _ in range(size)))


def make_source_code(path: pathlib.Path) -> None:
    src_dir = HERE.parent / "src"
    chunks = []
    for py_file in sorted(src_dir.rglob("*.py")):
        chunks.append(py_file.read_text())
    path.write_text("\n".join(chunks) * 10)


def make_dna_like(path: pathlib.Path, size: int = 200_000, seed: int = 7) -> None:
    rng = random.Random(seed)
    path.write_text("".join(rng.choice("ACGT") for _ in range(size)))


def main() -> None:
    FIXTURES_DIR.mkdir(exist_ok=True)
    make_english_repeated(FIXTURES_DIR / "english_repeated.txt")
    make_random_bytes(FIXTURES_DIR / "random_bytes.bin")
    make_source_code(FIXTURES_DIR / "source_code.py")
    make_dna_like(FIXTURES_DIR / "dna_like.txt")
    for f in sorted(FIXTURES_DIR.iterdir()):
        print(f"{f.name}: {f.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
