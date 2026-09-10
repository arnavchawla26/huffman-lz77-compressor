"""huffman_lz77 — a from-scratch general-purpose file compressor combining
canonical Huffman coding with LZ77 sliding-window matching.

Public API:
    compress(data: bytes) -> bytes
    decompress(blob: bytes) -> bytes
    compress_file(input_path, output_path) -> (original_size, compressed_size)
    decompress_file(input_path, output_path) -> (compressed_size, original_size)
"""
from .format import CorruptStreamError, compress, compress_file, decompress, decompress_file

__all__ = [
    "compress",
    "decompress",
    "compress_file",
    "decompress_file",
    "CorruptStreamError",
]

__version__ = "0.1.0"
