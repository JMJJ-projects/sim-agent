"""Tests for per-run artifacts (R-AG-7)."""

import base64
import json
from pathlib import Path

from simagent.artifacts import ArtifactWriter
from simagent.graph import solve
from simagent.llm import ScriptedChatModel
from simagent.nodes import AgentDeps
from simagent.runners.base import Runner, RunResult

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


class CannedRunner(Runner):
    """Fails the first run, then succeeds with a result and a PNG."""

    name = "canned"

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        self.calls += 1
        if self.calls == 1:
            return RunResult(1, "", "Traceback\nValueError: bad", None, False, 0.2, runner="canned")
        files = {
            "plot.png": base64.b64encode(PNG).decode(),
            "../evil.png": base64.b64encode(PNG).decode(),
            "broken.png": "%%%not-base64",
        }
        return RunResult(
            0, "T=0.3\n", "", {"answer": 0.3, "data": {}}, False, 0.3, runner="canned", files=files
        )


def test_artifacts_written_per_attempt(tmp_path: Path) -> None:
    """Covers R-AG-7."""
    replies = ["First.\n```python\nx = 1\n```", "Second.\n```python\nx = 2\n```"]
    writer = ArtifactWriter(tmp_path / "runs", {"provider": "fake", "model": "scripted"})
    deps = AgentDeps(
        model=ScriptedChatModel(replies=replies),
        runner=CannedRunner(),
        provider="fake",
        model_name="scripted",
        hooks=[writer],
    )
    final = solve("req", deps)
    assert final["status"] == "solved"

    run_dirs = list((tmp_path / "runs").iterdir())
    assert run_dirs == [writer.dir]
    a1, a2 = writer.dir / "attempt_1", writer.dir / "attempt_2"
    assert (a1 / "script.py").read_text(encoding="utf-8") == "x = 1\n"
    assert "ValueError: bad" in (a1 / "stderr.txt").read_text(encoding="utf-8")
    assert "exited with code 1" in (a1 / "error.txt").read_text(encoding="utf-8")
    assert not (a1 / "result.json").exists()
    assert json.loads((a2 / "result.json").read_text(encoding="utf-8"))["answer"] == 0.3
    assert (a2 / "stdout.txt").read_text(encoding="utf-8") == "T=0.3\n"
    assert (a2 / "reply.md").read_text(encoding="utf-8").startswith("Second.")
    assert sorted(p.name for p in (a2 / "files").iterdir()) == ["plot.png"]
    assert (a2 / "files" / "plot.png").read_bytes() == PNG
    assert not (tmp_path / "runs" / "evil.png").exists()

    trace = json.loads((writer.dir / "trace.json").read_text(encoding="utf-8"))
    assert trace["status"] == "solved"
    assert trace["provider"] == "fake"
    assert [a["outcome"] for a in trace["attempts"]] == ["run_failed", "ok"]
    assert trace["attempts"][0]["metrics"]["input_tokens"] is None
    assert "latency_s" in trace["attempts"][0]["metrics"]
    assert trace["attempts"][1]["run"]["duration_s"] == 0.3
    assert trace["totals"]["model_calls"] == 2

    final_json = json.loads((writer.dir / "final.json").read_text(encoding="utf-8"))
    assert final_json["answer"] == 0.3
    assert final_json["files"] == ["../evil.png", "broken.png", "plot.png"]
