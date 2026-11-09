"""Run facts for results headers: code commit and Ollama model digest (R-STAT-2)."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from simagent.evaluation import runinfo

ROOT = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_code_commit_clean_and_dirty(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "f.txt").write_text("a", encoding="utf-8")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-q", "-m", "c")
    clean = runinfo.code_commit(tmp_path)
    assert clean is not None
    assert len(clean) == 12
    (tmp_path / "untracked.txt").write_text("x", encoding="utf-8")
    assert runinfo.code_commit(tmp_path) == clean  # untracked files don't count
    (tmp_path / "f.txt").write_text("b", encoding="utf-8")
    assert runinfo.code_commit(tmp_path) == clean + "-dirty"


def test_code_commit_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert runinfo.code_commit(tmp_path) is None  # not a repository
    monkeypatch.setattr(runinfo.shutil, "which", lambda _: None)
    assert runinfo.code_commit(ROOT) is None


TAGS = {
    "models": [
        {
            "name": "qwen2.5-coder:3b",
            "model": "qwen2.5-coder:3b",
            "digest": "f72c60cabf62",
            "details": {"quantization_level": "Q4_K_M", "parameter_size": "3.1B"},
        },
        {"name": "llama3:latest", "digest": "d1", "details": {}},
    ]
}


def test_ollama_model_info() -> None:
    urls: list[str] = []

    def fetch(url: str) -> Any:
        urls.append(url)
        return TAGS

    info = runinfo.ollama_model_info("http://h:11434/", "qwen2.5-coder:3b", fetch)
    assert info == {"digest": "f72c60cabf62", "quantization": "Q4_K_M", "parameter_size": "3.1B"}
    assert urls == ["http://h:11434/api/tags"]
    assert runinfo.ollama_model_info("http://h", "llama3", fetch) == {
        "digest": "d1",
        "quantization": None,
        "parameter_size": None,
    }
    assert runinfo.ollama_model_info("http://h", "missing:1b", fetch) is None


def test_ollama_model_info_unreachable() -> None:
    def fetch(url: str) -> Any:
        raise OSError("connection refused")

    assert runinfo.ollama_model_info("http://h", "m", fetch) is None
    assert runinfo.ollama_model_info("http://h", "m", lambda url: ["not", "a", "dict"]) is None


PS = {
    "models": [
        {"name": "qwen2.5-coder:7b", "size": 6_000_000_000, "size_vram": 3_500_000_000},
        {"name": "other:1b", "size": 1, "size_vram": 1},
    ]
}


def test_ollama_loaded_reads_size_and_vram() -> None:
    """Covers R-QV-2: per-model size and size_vram from /api/ps."""
    urls: list[str] = []

    def fetch(url: str) -> Any:
        urls.append(url)
        return PS

    assert runinfo.ollama_loaded("http://h/", "qwen2.5-coder:7b", fetch) == (
        6_000_000_000,
        3_500_000_000,
    )
    assert urls == ["http://h/api/ps"]
    assert runinfo.ollama_loaded("http://h", "missing:3b", fetch) is None
    assert runinfo.ollama_loaded("http://h", "m", lambda u: {"models": [{"name": "m"}]}) is None

    def down(url: str) -> Any:
        raise OSError("refused")

    assert runinfo.ollama_loaded("http://h", "m", down) is None
