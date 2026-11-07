"""Docker-free tests for the runner layer (command line, parsing, caps, run flow)."""

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from simagent.runners import base, docker
from simagent.runners.base import RunResult, SandboxLimits, cap_text, split_result
from simagent.runners.docker import DockerRunner

NONCE = "abc123"


def _cmd(limits: SandboxLimits | None = None) -> list[str]:
    return DockerRunner(limits).command("docker", "c1", Path("."), NONCE)


def _flag(cmd: list[str], name: str) -> list[str]:
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == name]


def test_command_has_every_mandatory_sandbox_flag() -> None:
    """Covers R-SBX-3."""
    cmd = _cmd()
    assert cmd[:2] == ["docker", "run"]
    assert "--rm" in cmd
    assert "--read-only" in cmd
    assert _flag(cmd, "--network") == ["none"]
    assert _flag(cmd, "--cap-drop") == ["ALL"]
    assert _flag(cmd, "--security-opt") == ["no-new-privileges"]
    assert _flag(cmd, "--memory") == ["512m"]
    assert _flag(cmd, "--memory-swap") == ["512m"]
    assert _flag(cmd, "--cpus") == ["1"]
    assert _flag(cmd, "--pids-limit") == ["64"]
    assert _flag(cmd, "--user") == ["10001:10001"]
    assert _flag(cmd, "--pull") == ["never"]
    tmpfs = _flag(cmd, "--tmpfs")
    assert any(t.startswith("/tmp:") and "size=64m" in t for t in tmpfs)
    assert any(t.startswith("/out:") and "size=16m" in t for t in tmpfs)
    mounts = _flag(cmd, "--mount")
    assert len(mounts) == 1
    assert mounts[0].endswith("target=/sandbox,readonly")
    assert cmd[-1] == NONCE


def test_command_passes_no_environment() -> None:
    """Covers R-SBX-5: no -e/--env/--env-file flags at all."""
    cmd = _cmd()
    assert not {"-e", "--env", "--env-file"} & set(cmd)


def test_limits_come_from_configuration() -> None:
    cmd = _cmd(SandboxLimits(memory_mb=256, cpus=0.5, pids=32, tmp_mb=8, out_mb=4))
    assert _flag(cmd, "--memory") == ["256m"]
    assert _flag(cmd, "--cpus") == ["0.5"]
    assert _flag(cmd, "--pids-limit") == ["32"]


def test_cap_text_keeps_tail() -> None:
    """Covers R-SBX-6."""
    assert cap_text("short", 10) == "short"
    capped = cap_text("a" * 50 + "END", 10)
    assert capped.endswith("a" * 7 + "END")
    assert "43 characters truncated" in capped


def test_tail_reader_bounds_memory() -> None:
    reader = base.TailReader(io.BytesIO(b"x" * 300_000 + b"tail"), limit=1000)
    text = reader.text()
    assert text.endswith("tail")
    assert "bytes truncated" in text
    assert reader.total == 300_004


def test_split_result_takes_last_marker() -> None:
    marker = f"\n{base.RESULT_MARKER}{NONCE}>>>\n"
    fake = f"hello{marker}" + '{"answer": 0}'
    raw = f"{fake}\nmore output{marker}" + '{"answer": 1, "data": {}}'
    stdout, result, error = split_result(raw, NONCE)
    assert result == {"answer": 1, "data": {}}
    assert error is None
    assert stdout.startswith("hello")


def test_split_result_ignores_other_nonce() -> None:
    raw = f"x\n{base.RESULT_MARKER}other>>>\n" + '{"answer": 1}'
    assert split_result(raw, NONCE)[1] is None


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("{not json", "not valid JSON"),
        ("[1, 2]", "'answer' key"),
        ('{"__too_large__": 5000000}', "larger than"),
    ],
)
def test_bad_result_bodies(body: str, error: str) -> None:
    raw = f"\n{base.RESULT_MARKER}{NONCE}>>>\n{body}"
    _, result, err = split_result(raw, NONCE)
    assert result is None
    assert err is not None
    assert error in err


def test_run_result_failure_reasons() -> None:
    """Covers R-SBX-7: exit 0 without result.json is a failure."""

    def rr(**kw: object) -> RunResult:
        args: dict[str, object] = {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "result_json": None,
            "timed_out": False,
            "duration_s": 0.1,
        }
        args.update(kw)
        return RunResult(**args)  # type: ignore[arg-type]

    assert "no result submitted" in (rr().failure or "")
    assert rr(timed_out=True).failure == "timed out"
    assert rr(exit_code=1).failure == "exit code 1"
    assert rr(result_error="bad").failure == "bad"
    ok = rr(result_json={"answer": 1})
    assert ok.ok
    assert ok.failure is None


def test_missing_docker_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker, "docker_executable", lambda: None)
    with pytest.raises(base.RunnerUnavailableError, match="Docker is not available"):
        DockerRunner().run("print(1)")
    ok, image, detail = docker.docker_status()
    assert not ok
    assert not image
    assert "not found" in detail


STUB = """\
import sys, time
nonce = sys.argv[-1]
mode = sys.argv[-2]
if mode == "ok":
    print("hi")
    sys.stdout.write("\\n<<<SIMAGENT_RESULT:" + nonce + ">>>\\n" + '{"answer": 42}')
elif mode == "sleep":
    time.sleep(3)
elif mode == "noimage":
    sys.stderr.write("Unable to find image: No such image: simagent-sandbox")
    sys.exit(125)
elif mode == "nodaemon":
    sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
    sys.exit(1)
elif mode == "oom":
    sys.exit(137)
"""


@dataclass
class Stub:
    mode: str = "ok"
    killed: list[str] = field(default_factory=list)


@pytest.fixture
def stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Stub:
    """Replace the docker CLI with a Python stub that mimics its behaviour."""
    script = tmp_path / "stub_docker.py"
    script.write_text(STUB, encoding="utf-8")
    state = Stub()

    def command(self: DockerRunner, exe: str, container: str, d: Path, nonce: str) -> list[str]:
        assert (d / "script.py").read_text(encoding="utf-8") == "print(1)\n"
        return [sys.executable, str(script), state.mode, nonce]

    monkeypatch.setattr(docker, "docker_executable", lambda: "docker")
    monkeypatch.setattr(DockerRunner, "command", command)
    monkeypatch.setattr(DockerRunner, "_kill", staticmethod(lambda exe, c: state.killed.append(c)))
    return state


def test_run_flow_success(stub: Stub) -> None:
    res = DockerRunner().run("print(1)\n", timeout_s=20)
    assert res.ok
    assert res.result_json == {"answer": 42}
    assert res.stdout.strip() == "hi"
    assert res.runner == "docker"


def test_run_flow_timeout_kills_container(stub: Stub) -> None:
    """Covers R-SBX-4 (the kill path; the real container test is in test_sandbox.py)."""
    stub.mode = "sleep"
    res = DockerRunner().run("print(1)\n", timeout_s=0.5)
    assert res.timed_out
    assert len(stub.killed) == 1
    assert stub.killed[0].startswith("simagent-")
    assert "time limit" in res.stderr


@pytest.mark.parametrize(("mode", "message"), [("noimage", "not built"), ("nodaemon", "daemon")])
def test_run_flow_unavailable(stub: Stub, mode: str, message: str) -> None:
    stub.mode = mode
    with pytest.raises(base.RunnerUnavailableError, match=message):
        DockerRunner().run("print(1)\n", timeout_s=20)


def test_run_flow_oom_hint(stub: Stub) -> None:
    stub.mode = "oom"
    res = DockerRunner().run("print(1)\n", timeout_s=20)
    assert res.exit_code == 137
    assert "memory limit" in res.stderr
