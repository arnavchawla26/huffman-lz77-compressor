"""Command-line interface: `hzc compress` / `hzc decompress`."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .format import CorruptStreamError, compress_file, decompress_file

DEFAULT_SUFFIX = ".hz77"


def _default_output_for_compress(input_path: str) -> str:
    return input_path + DEFAULT_SUFFIX


def _default_output_for_decompress(input_path: str) -> str:
    if input_path.endswith(DEFAULT_SUFFIX):
        return input_path[: -len(DEFAULT_SUFFIX)]
    return input_path + ".out"


def _cmd_compress(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = args.output or _default_output_for_compress(input_path)
    if not Path(input_path).exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 1
    if Path(output_path).resolve() == Path(input_path).resolve():
        print("error: refusing to overwrite the input file", file=sys.stderr)
        return 1
    start = time.perf_counter()
    original_size, compressed_size = compress_file(input_path, output_path, max_chain=args.max_chain)
    elapsed = time.perf_counter() - start
    if args.verbose or not args.quiet:
        ratio = (compressed_size / original_size) if original_size else 1.0
        saved_pct = (1 - ratio) * 100
        print(
            f"{input_path}: {original_size:,} -> {compressed_size:,} bytes "
            f"({saved_pct:.1f}% smaller, {elapsed:.2f}s) -> {output_path}"
        )
    return 0


def _cmd_decompress(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = args.output or _default_output_for_decompress(input_path)
    if not Path(input_path).exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 1
    if Path(output_path).resolve() == Path(input_path).resolve():
        print("error: refusing to overwrite the input file", file=sys.stderr)
        return 1
    start = time.perf_counter()
    try:
        compressed_size, original_size = decompress_file(input_path, output_path)
    except CorruptStreamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - start
    if args.verbose or not args.quiet:
        print(
            f"{input_path}: {compressed_size:,} -> {original_size:,} bytes "
            f"({elapsed:.2f}s) -> {output_path}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hzc",
        description="A from-scratch Huffman + LZ77 general-purpose file compressor.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compress_parser = subparsers.add_parser("compress", help="compress a file")
    compress_parser.add_argument("input", help="path to the file to compress")
    compress_parser.add_argument(
        "-o", "--output", help="output path (default: <input>.hz77)"
    )
    compress_parser.add_argument(
        "--max-chain",
        type=int,
        default=128,
        help="max LZ77 match candidates examined per position (default: 128; "
        "higher = better ratio, slower)",
    )
    compress_parser.add_argument("-v", "--verbose", action="store_true")
    compress_parser.add_argument("-q", "--quiet", action="store_true")
    compress_parser.set_defaults(func=_cmd_compress)

    decompress_parser = subparsers.add_parser("decompress", help="decompress a file")
    decompress_parser.add_argument("input", help="path to the .hz77 file to decompress")
    decompress_parser.add_argument(
        "-o", "--output", help="output path (default: strip .hz77, else <input>.out)"
    )
    decompress_parser.add_argument("-v", "--verbose", action="store_true")
    decompress_parser.add_argument("-q", "--quiet", action="store_true")
    decompress_parser.set_defaults(func=_cmd_decompress)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
