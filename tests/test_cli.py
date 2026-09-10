import subprocess
import sys

import pytest


def run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "huffman_lz77.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def sample_file(tmp_path):
    p = tmp_path / "input.txt"
    p.write_text("the quick brown fox jumps over the lazy dog. " * 100)
    return p


def test_compress_then_decompress_round_trip(tmp_path, sample_file):
    result = run_cli(["compress", str(sample_file)], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    compressed = sample_file.with_suffix(sample_file.suffix + ".hz77")
    assert compressed.exists()
    assert compressed.stat().st_size < sample_file.stat().st_size

    result2 = run_cli(["decompress", str(compressed)], cwd=tmp_path)
    assert result2.returncode == 0, result2.stderr
    restored = tmp_path / "input.txt"
    assert restored.read_bytes() == sample_file.read_bytes()


def test_compress_custom_output_path(tmp_path, sample_file):
    out = tmp_path / "custom.bin"
    result = run_cli(["compress", str(sample_file), "-o", str(out)], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert out.exists()


def test_decompress_custom_output_path(tmp_path, sample_file):
    compressed = tmp_path / "c.hz77"
    run_cli(["compress", str(sample_file), "-o", str(compressed)], cwd=tmp_path)
    out = tmp_path / "restored.txt"
    result = run_cli(["decompress", str(compressed), "-o", str(out)], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == sample_file.read_bytes()


def test_compress_missing_input_errors(tmp_path):
    result = run_cli(["compress", str(tmp_path / "nope.txt")], cwd=tmp_path)
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_decompress_refuses_corrupt_file(tmp_path):
    bogus = tmp_path / "bad.hz77"
    bogus.write_bytes(b"not a real hz77 stream")
    result = run_cli(["decompress", str(bogus)], cwd=tmp_path)
    assert result.returncode != 0
    assert "error" in result.stderr.lower()


def test_refuses_to_overwrite_input(tmp_path, sample_file):
    result = run_cli(["compress", str(sample_file), "-o", str(sample_file)], cwd=tmp_path)
    assert result.returncode != 0
    assert "refus" in result.stderr.lower()


def test_verbose_output_reports_sizes(tmp_path, sample_file):
    result = run_cli(["compress", str(sample_file), "-v"], cwd=tmp_path)
    assert result.returncode == 0
    assert "->" in result.stdout
    assert "%" in result.stdout


def test_quiet_suppresses_output(tmp_path, sample_file):
    result = run_cli(["compress", str(sample_file), "-q"], cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_empty_file_round_trip(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    run_cli(["compress", str(empty)], cwd=tmp_path)
    compressed = tmp_path / "empty.txt.hz77"
    assert compressed.exists()
    result = run_cli(["decompress", str(compressed)], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "empty.txt").read_bytes() == b""


def test_binary_file_round_trip(tmp_path):
    binary = tmp_path / "data.bin"
    binary.write_bytes(bytes(range(256)) * 20)
    run_cli(["compress", str(binary)], cwd=tmp_path)
    compressed = tmp_path / "data.bin.hz77"
    result = run_cli(["decompress", str(compressed), "-o", str(tmp_path / "data.bin.restored")], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data.bin.restored").read_bytes() == binary.read_bytes()
