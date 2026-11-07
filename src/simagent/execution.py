"""Policy check followed by a sandboxed run: the only path from code to execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simagent.policy import PolicyResult, check
from simagent.runners.base import DEFAULT_TIMEOUT_S, Runner, RunResult


@dataclass(frozen=True)
class Execution:
    """Outcome of ``execute``: the policy verdict and, if it passed, the run."""

    policy: PolicyResult
    run: RunResult | None

    @property
    def ok(self) -> bool:
        return self.policy.ok and self.run is not None and self.run.ok

    def to_dict(self, *, include_files: bool = False) -> dict[str, Any]:
        """JSON-friendly report. PNG files are listed by name unless ``include_files``."""
        run = self.run
        report: dict[str, Any] = {
            "ok": self.ok,
            "failure": self.failure,
            "policy_violations": [str(v) for v in self.policy.violations],
            "run": None,
        }
        if run is not None:
            report["run"] = {
                "runner": run.runner,
                "exit_code": run.exit_code,
                "timed_out": run.timed_out,
                "duration_s": round(run.duration_s, 3),
                "result": run.result_json,
                "result_error": run.result_error,
                "stdout": run.stdout,
                "stderr": run.stderr,
                "files": dict(run.files) if include_files else sorted(run.files),
                "warnings": run.warnings,
            }
        return report

    @property
    def failure(self) -> str | None:
        if not self.policy.ok:
            return "policy violation"
        assert self.run is not None
        return self.run.failure


def execute(code: str, runner: Runner, timeout_s: float = DEFAULT_TIMEOUT_S) -> Execution:
    """Check ``code`` with the static policy and, only if it passes, run it with ``runner``."""
    verdict = check(code)
    if not verdict.ok:
        return Execution(policy=verdict, run=None)
    return Execution(policy=verdict, run=runner.run(code, timeout_s=timeout_s))
