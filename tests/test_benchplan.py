"""v2 benchmark plan: expansion, validation, progress and ETA (PLAN-v2 2.4)."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from simagent.evaluation import benchplan
from simagent.evaluation.benchplan import (
    Progress,
    eta_s,
    expand,
    format_duration,
    median_task_s,
    progress,
    task_seconds,
)
from simagent.evaluation.harness import HEADER_KIND
from simagent.evaluation.tasks import load_task_set
from simagent.prompts import PROMPT_VERSION_LATEST

ROOT = Path(__file__).resolve().parents[1]


def _run(**kw: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "round": "6.1",
        "provider": "ollama",
        "model": "m:3b",
        "mode": "repair",
        "task_set": "dev",
        "seeds": [0, 1],
    }
    entry.update(kw)
    return entry


def test_expand_one_unit_per_task_set_and_seed() -> None:
    units = expand({"runs": [_run(task_set="all", delay_s=30, vram=True)]}, latest_prompt=2)
    assert [(u.task_set, u.seed) for u in units] == [
        ("dev", 0),
        ("dev", 1),
        ("heldout", 0),
        ("heldout", 1),
    ]
    assert units[0].name == "ollama-m_3b-p2-repair-dev-s0"
    assert units[0].delay_s == 30.0
    assert units[0].vram
    assert expand({"runs": [_run(prompt_version=1)]}, 2)[0].prompt_version == 1


def test_unit_command_matches_evaluate_flags(tmp_path: Path) -> None:
    unit = expand({"runs": [_run(delay_s=30, vram=True)]}, 2)[0]
    args = unit.evaluate_args(tmp_path / "r", tmp_path / "a")
    assert args[args.index("--seeds") + 1] == "0"
    assert args[args.index("--task-set") + 1] == "dev"
    assert args[args.index("--delay") + 1] == "30"
    assert "--resume" in args
    assert "--vram" in args
    plain = expand({"runs": [_run()]}, 2)[0].evaluate_args(tmp_path, tmp_path)
    assert "--delay" not in plain
    assert "--vram" not in plain


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"mode": "nope"}, "mode"),
        ({"provider": "nope"}, "provider"),
        ({"task_set": "nope"}, "task set"),
        ({"seeds": []}, "seeds"),
        ({"seeds": [0, 0]}, "seeds"),
        ({"seeds": [-1]}, "seeds"),
        ({"seeds": "0"}, "seeds"),
        ({"extra": 1}, "unknown"),
    ],
)
def test_plan_validation(kw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        expand({"runs": [_run(**kw)]}, 2)


def test_plan_rejects_duplicate_files() -> None:
    with pytest.raises(ValueError, match="twice"):
        expand({"runs": [_run(), _run(seeds=[1])]}, 2)


def test_committed_v2_plan_is_valid() -> None:
    """The committed plan expands: dev + held-out x seeds for each run (PLAN-v2 Phase 6)."""
    units = expand(benchplan.load_plan(ROOT / "data" / "bench_plan_v2.json"), 2)
    local = [u for u in units if u.provider == "ollama" and u.round == "6.1"]
    hosted = [u for u in units if u.provider == "groq"]
    assert len(local) == 2 * 3 * 2 * 5  # 2 models x 3 modes x 2 task sets x 5 seeds
    assert len(hosted) == 3 * 2 * 3  # 3 modes x 2 task sets x 3 seeds
    quant = [u for u in units if u.round == "6.3"]
    assert len(quant) == 2 * 2 * 3  # 2 models x 2 task sets x 3 seeds, verify only
    assert {u.mode for u in quant} == {"verify"}
    assert {u.mode for u in units} == {"baseline", "repair", "verify"}


def _write(path: Path, latencies: list[float], header: bool = True) -> None:
    lines = [json.dumps({"kind": HEADER_KIND})] if header else []
    lines += [
        json.dumps({"task_id": f"t{i}", "passed": True, "latency_s": s})
        for i, s in enumerate(latencies)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_progress_and_eta(tmp_path: Path) -> None:
    units = expand(
        {
            "runs": [
                _run(seeds=[0, 1]),
                _run(mode="baseline", seeds=[0]),
                _run(model="other:1b", seeds=[0]),
            ]
        },
        2,
    )
    a0, a1, b0, c0 = units
    _write(tmp_path / f"{a0.name}.jsonl", [10.0, 20.0, 30.0])  # complete (3 tasks)
    _write(tmp_path / f"{a1.name}.jsonl", [40.0])  # partial
    rows = progress(units, tmp_path, {"dev": 3, "heldout": 2})
    assert [r.state for r in rows] == ["complete", "partial", "not started", "not started"]
    timings = task_seconds(tmp_path, units)
    assert median_task_s(a1, timings) == 25.0  # same provider/model/mode: 10, 20, 30, 40
    assert median_task_s(b0, timings) == 25.0  # falls back to same provider/model
    assert median_task_s(c0, timings) is None  # no timing data for that model
    known, unknown = eta_s(rows, timings)
    assert known == 2 * 25.0 + 3 * 25.0  # a1: 2 tasks left, b0: 3 tasks left
    assert unknown == 3  # c0
    assert eta_s([Progress(a0, 3, 3)], timings) == (0.0, 0)


def test_delay_counts_in_task_time(tmp_path: Path) -> None:
    unit = expand({"runs": [_run(seeds=[0], delay_s=30)]}, 2)[0]
    _write(tmp_path / f"{unit.name}.jsonl", [5.0], header=False)
    assert task_seconds(tmp_path, [unit]) == {unit: [35.0]}


def test_format_duration() -> None:
    assert format_duration(0) == "0 min"
    assert format_duration(59 * 60) == "59 min"
    assert format_duration(3 * 3600 + 7 * 60) == "3 h 07 min"


def _bench_module() -> Any:
    spec = importlib.util.spec_from_file_location("bench", ROOT / "scripts" / "bench.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bench_script_status_select_and_promote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bench = _bench_module()
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"runs": [_run(seeds=[0])]}), encoding="utf-8")
    staging = tmp_path / "staging"
    monkeypatch.setattr(bench, "STAGING", staging)
    monkeypatch.setattr(bench, "RESULTS", tmp_path / "results")
    assert bench.main(["status", "--plan", str(plan)]) == 0
    out = capsys.readouterr().out
    assert "not started" in out
    assert "without timing data" in out

    unit = expand(json.loads(plan.read_text()), PROMPT_VERSION_LATEST)[0]
    assert bench.select([unit], "other", None) == []
    assert bench.select([unit], None, "6.1") == [unit]
    staging.mkdir()
    _write(staging / f"{unit.name}.jsonl", [1.0] * len(load_task_set("dev", ROOT)))
    assert bench.main(["promote", "--plan", str(plan)]) == 0
    assert (tmp_path / "results" / f"{unit.name}.jsonl").is_file()


def test_bench_default_action_is_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`python scripts/bench.py --plan ...` (CLAUDE.md) only reports; it never starts runs."""
    bench = _bench_module()
    monkeypatch.setattr(bench, "STAGING", tmp_path)
    assert bench.main(["--plan", str(ROOT / "data" / "bench_plan_v2.json")]) == 0
    assert "ETA" in capsys.readouterr().out
