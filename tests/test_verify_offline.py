"""scripts/verify_offline.py: the verifier over recorded results without traces (CHECKPOINT B)."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("vo", ROOT / "scripts" / "verify_offline.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rec(task_id: str, answer: Any, passed: bool, status: str = "solved") -> str:
    return json.dumps({"task_id": task_id, "answer": answer, "passed": passed, "status": status})


def test_counts_without_traces(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lines = [
        _rec("ambig_01", 0.42, False),  # unknown material answered with a number: caught
        _rec("single_01", 1.7, False),  # a fraction above 1: caught by V-RANGE
        _rec("single_02", 0.11, False),  # plausible but wrong: needs a trace, not caught
        _rec("single_03", 0.3, True),  # correct: no false alarm
        _rec("adv_01", None, True, status="refused"),  # not an answer: skipped
    ]
    (tmp_path / "r.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    vo = _script()
    prompts = {t.id: t.prompt for t in vo.load_task_set("dev", ROOT)}
    row = vo.analyse_file(tmp_path / "r.jsonl", prompts)
    assert (row["caught"], row["wrong_answers"]) == (2, 3)
    assert (row["false_alarms"], row["correct_answers"]) == (0, 1)
    assert row["by_check"] == {"V-UNKNOWN": 1, "V-RANGE": 1}
    assert vo.main(["--results-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "trace-free checks only" in out
    assert "total | 2/3 | 0/1" in out
    assert vo.main(["--results-dir", str(tmp_path / "none")]) == 2
