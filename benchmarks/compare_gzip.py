"""Benchmarks hzc against Python's stdlib gzip (zlib/DEFLATE at level 9) on
the fixture files produced by generate_fixtures.py, reporting compression
ratio and wall-clock time for both.

    python benchmarks/generate_fixtures.py
    python benchmarks/compare_gzip.py
"""
from __future__ import annotations

import gzip
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from huffman_lz77.format import compress, decompress  # noqa: E402

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


def bench_one(path: pathlib.Path) -> dict:
    data = path.read_bytes()

    t0 = time.perf_counter()
    hz_blob = compress(data)
    t1 = time.perf_counter()
    restored = decompress(hz_blob)
    t2 = time.perf_counter()
    assert restored == data, f"hzc round-trip FAILED for {path.name}"

    t3 = time.perf_counter()
    gz_blob = gzip.compress(data, compresslevel=9)
    t4 = time.perf_counter()
    gzip.decompress(gz_blob)
    t5 = time.perf_counter()

    return {
        "name": path.name,
        "original": len(data),
        "hz_size": len(hz_blob),
        "hz_ratio": len(hz_blob) / len(data) if data else float("nan"),
        "hz_compress_s": t1 - t0,
        "hz_decompress_s": t2 - t1,
        "gz_size": len(gz_blob),
        "gz_ratio": len(gz_blob) / len(data) if data else float("nan"),
        "gz_compress_s": t4 - t3,
        "gz_decompress_s": t5 - t4,
    }


def main() -> None:
    if not FIXTURES_DIR.exists() or not any(FIXTURES_DIR.iterdir()):
        print("No fixtures found. Run: python benchmarks/generate_fixtures.py")
        raise SystemExit(1)

    rows = [bench_one(p) for p in sorted(FIXTURES_DIR.iterdir()) if p.is_file()]

    header = f"{'file':<22}{'orig':>10}{'hzc':>10}{'gzip':>10}{'hzc/gzip':>10}{'hzc s (c/d)':>16}{'gzip s (c/d)':>16}"
    print(header)
    print("-" * len(header))
    for r in rows:
        ratio_vs_gzip = r["hz_size"] / r["gz_size"] if r["gz_size"] else float("nan")
        print(
            f"{r['name']:<22}{r['original']:>10,}{r['hz_size']:>10,}{r['gz_size']:>10,}"
            f"{ratio_vs_gzip:>10.2f}"
            f"{r['hz_compress_s']:>8.3f}/{r['hz_decompress_s']:<7.3f}"
            f"{r['gz_compress_s']:>8.3f}/{r['gz_decompress_s']:<7.3f}"
        )

    print()
    print(
        "hzc/gzip < 1.0 means hzc produced a *smaller* file than gzip for that "
        "input; > 1.0 means gzip won. Timing columns are compress/decompress "
        "wall-clock seconds. hzc is a pure-Python reference implementation, so "
        "its speed is not expected to compete with zlib's C implementation --"
        " the comparison here is about compression ratio."
    )


if __name__ == "__main__":
    main()
