"""Tests for the in-sandbox result submission helper."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import photonsim as p
from simagent.io_helper import simagent_io


@pytest.fixture(autouse=True)
def out_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SIMAGENT_OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(simagent_io, "_submitted", False)
    return tmp_path / "out"


def _read(out_dir: Path) -> Any:
    return json.loads((out_dir / "result.json").read_text(encoding="utf-8"))


def test_submit_writes_result_json(out_dir: Path) -> None:
    """Covers R-SBX-7."""
    simagent_io.submit(0.25, thickness_cm=[1, 2], note="ok")
    assert _read(out_dir) == {"answer": 0.25, "data": {"thickness_cm": [1, 2], "note": "ok"}}
    assert not (out_dir / "result.json.tmp").exists()


def test_numpy_and_result_objects_are_converted(out_dir: Path) -> None:
    res = p.simulate(p.Slab([p.Layer("water", 1.0)]), 1.0, 100, seed=1)
    simagent_io.submit(np.float64(0.5), arr=np.arange(3), res=res, pair=(1, np.int64(2)))
    got = _read(out_dir)
    assert got["answer"] == 0.5
    assert got["data"]["arr"] == [0, 1, 2]
    assert got["data"]["res"]["n_photons"] == 100
    assert got["data"]["pair"] == [1, 2]


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (float("nan"), "NaN"),
        ({1: "x"}, "non-string key"),
        ({1, 2}, "not JSON-serialisable"),
        ([object()], r"answer\[0\]"),
    ],
)
def test_invalid_values_rejected(answer: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        simagent_io.submit(answer)


def test_submit_only_once() -> None:
    simagent_io.submit(1)
    with pytest.raises(RuntimeError, match="only be called once"):
        simagent_io.submit(2)


def test_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simagent_io, "MAX_RESULT_BYTES", 50)
    with pytest.raises(ValueError, match="larger than 50 bytes"):
        simagent_io.submit("x" * 100)


def test_none_and_bool_pass_through(out_dir: Path) -> None:
    simagent_io.submit(None, flag=True)
    assert _read(out_dir) == {"answer": None, "data": {"flag": True}}


@pytest.fixture
def tracing(monkeypatch: pytest.MonkeyPatch) -> Any:
    from photonsim import _provenance

    monkeypatch.setenv(simagent_io.TRACE_FLAG, "1")
    _provenance.reset(enabled=True)
    yield _provenance
    _provenance.reset(enabled=False)


def test_submit_writes_the_trace_beside_the_result(out_dir: Path, tracing: Any) -> None:
    """Covers R-TRACE-1: submit() writes photonsim's record to trace.json."""
    res = p.simulate(p.Slab([p.Layer("lead", 2.0)]), 1.0, 200, seed=3)
    simagent_io.submit(res.transmitted)
    trace = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    assert trace["n_calls"] == 1
    assert trace["calls"][0]["layers"] == [["lead", 2.0]]
    assert trace["calls"][0]["transmitted"] == res.transmitted
    assert not (out_dir / "trace.json.tmp").exists()


def test_submit_replaces_a_trace_written_by_the_script(out_dir: Path, tracing: Any) -> None:
    """Covers R-TRACE-3: a fake trace.json written before submit() is overwritten."""
    out_dir.mkdir(parents=True)
    fake = {"calls": [{"layers": [["water", 1.0]], "energy_mev": 1.0}]}
    (out_dir / "trace.json").write_text(json.dumps(fake), encoding="utf-8")
    p.simulate(p.Slab([p.Layer("iron", 3.0)]), 2.0, 100, seed=1)
    simagent_io.submit(1)
    trace = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    assert [c["layers"] for c in trace["calls"]] == [[["iron", 3.0]]]


def test_no_trace_when_recording_is_off(out_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(simagent_io.TRACE_FLAG, raising=False)
    simagent_io.submit(1)
    assert not (out_dir / "trace.json").exists()


def test_empty_trace_when_photonsim_was_never_imported(
    out_dir: Path, tracing: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    monkeypatch.delitem(sys.modules, "photonsim._provenance")
    simagent_io.submit(None, error="nothing to simulate")
    trace = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    assert trace["calls"] == []
    assert trace["n_calls"] == 0
