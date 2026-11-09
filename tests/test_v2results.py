"""Grouping v2 results files into configurations and their statistics (R-STAT-1..6)."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from simagent.evaluation.v2results import analyse, config_key, load_groups

ROOT = Path(__file__).resolve().parents[1]


def _header(mode: str, seed: int, task_set: str = "dev", **kw: Any) -> dict[str, Any]:
    header: dict[str, Any] = {
        "kind": "header",
        "provider": "fake",
        "model": "scripted",
        "prompt_version": 2,
        "task_set": task_set,
        "mode": mode,
        "temperature": 0.7,
        "max_attempts": 1 if mode == "baseline" else 4,
        "seed": seed,
    }
    header.update(kw)
    return header


def _write(root: Path, name: str, header: dict[str, Any] | None, passed: dict[str, bool]) -> None:
    lines = [json.dumps(header)] if header else []
    lines += [json.dumps({"task_id": t, "passed": p}) for t, p in passed.items()]
    (root / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fixture(root: Path) -> None:
    # baseline: t1 passes in both seeds, t2 never, t3 once; repair: t1, t2 always, t3 once.
    _write(root, "b0", _header("baseline", 0), {"t1": True, "t2": False, "t3": True})
    _write(root, "b1", _header("baseline", 1), {"t1": True, "t2": False, "t3": False})
    _write(root, "r0", _header("repair", 0), {"t1": True, "t2": True, "t3": False})
    _write(root, "r1", _header("repair", 1), {"t1": True, "t2": True, "t3": True})
    _write(root, "v1-history", None, {"t1": True})  # v1 file: ignored


def test_groups_by_header_not_file_name(tmp_path: Path) -> None:
    _fixture(tmp_path)
    groups = load_groups(tmp_path)
    assert sorted(k.mode for k in groups) == ["baseline", "repair"]
    assert all(sorted(seeds) == [0, 1] for seeds in groups.values())


def test_analyse_stats_and_paired_comparison(tmp_path: Path) -> None:
    """Covers R-STAT-3/4/5 end to end on a hand-checked fixture."""
    _fixture(tmp_path)
    configs, comparisons = analyse(load_groups(tmp_path))
    by_mode = {c.key.mode: c for c in configs}
    base, rep = by_mode["baseline"], by_mode["repair"]
    assert base.success.mean == pytest.approx(0.5)  # per task: 1, 0, 0.5
    assert rep.success.mean == pytest.approx(5 / 6)  # per task: 1, 1, 0.5
    assert (base.success.seed_min, base.success.seed_max) == (pytest.approx(1 / 3), 2 / 3)
    r = base.reliability
    assert (r.all_seeds, r.some_seeds, r.no_seed) == (1, 1, 1)
    assert len(comparisons) == 1
    cmp = comparisons[0]
    assert (cmp.a.mode, cmp.b.mode) == ("repair", "baseline")
    assert cmp.paired.diff == pytest.approx(1 / 3)  # per-task differences 0, 1, 0
    assert cmp.mcnemar_seed0 is not None
    assert (cmp.mcnemar_seed0.a_only, cmp.mcnemar_seed0.b_only) == (1, 1)  # t2 vs t3


def test_comparisons_only_within_the_same_setup(tmp_path: Path) -> None:
    _write(tmp_path, "b", _header("baseline", 0, task_set="dev"), {"t": True})
    _write(tmp_path, "r", _header("repair", 0, task_set="heldout"), {"t": True})
    _write(tmp_path, "r2", _header("repair", 1, task_set="dev", model="other"), {"t": True})
    _, comparisons = analyse(load_groups(tmp_path))
    assert comparisons == []


def test_missing_seed0_skips_mcnemar(tmp_path: Path) -> None:
    _write(tmp_path, "b", _header("baseline", 1), {"t": True})
    _write(tmp_path, "r", _header("repair", 1), {"t": False})
    _, comparisons = analyse(load_groups(tmp_path))
    assert comparisons[0].mcnemar_seed0 is None


def test_duplicate_seed_is_an_error(tmp_path: Path) -> None:
    _write(tmp_path, "a", _header("repair", 0), {"t": True})
    _write(tmp_path, "b", _header("repair", 0), {"t": True})
    with pytest.raises(ValueError, match="appears twice"):
        load_groups(tmp_path)


def test_config_key_label() -> None:
    key = config_key(_header("verify", 0, task_set="heldout"))
    assert key.label == "fake/scripted p2 verify [heldout]"
    assert key.setup == ("fake", "scripted", 2, "heldout", 0.7)


def _stats_script() -> Any:
    spec = importlib.util.spec_from_file_location("stats_v2", ROOT / "scripts" / "stats_v2.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stats_script(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Covers R-STAT-6 in the printed output: a CI that includes 0 is not an improvement."""
    _fixture(tmp_path)
    script = _stats_script()
    assert script.main(["--results-dir", str(tmp_path), "--min-seeds", "2"]) == 0
    out = capsys.readouterr().out
    assert "fake/scripted p2 repair [dev] | 3 x 2 |  83.3 %" in out
    assert "no measurable difference" in out
    assert "improvement" not in out
    assert "p=1.0000" in out
    assert script.main(["--results-dir", str(tmp_path), "--min-seeds", "3"]) == 2
    assert script.main(["--results-dir", str(tmp_path / "empty")]) == 2
    _write(tmp_path, "dupe", _header("repair", 0), {"t1": True})
    assert script.main(["--results-dir", str(tmp_path)]) == 2
