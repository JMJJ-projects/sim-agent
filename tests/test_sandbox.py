"""Sandbox isolation tests: run real containers (R-SBX-3..7, R-POL-5).

These tests call the runner directly, i.e. with the static policy *disabled*, to prove the
sandbox holds on its own. They need Docker and the ``simagent-sandbox`` image
(`make sandbox-image`) and are skipped otherwise.
"""

import base64
import json
import subprocess
import textwrap

import pytest

from simagent.policy import check
from simagent.runners import DockerRunner, RunResult, SandboxLimits
from simagent.runners.docker import docker_executable

pytestmark = pytest.mark.docker


def run(code: str, timeout_s: float = 30.0, limits: SandboxLimits | None = None) -> RunResult:
    return DockerRunner(limits).run(textwrap.dedent(code), timeout_s=timeout_s)


def answer(res: RunResult) -> object:
    assert res.result_json is not None, f"no result: {res.failure}\n{res.stderr}"
    return res.result_json["answer"]


def test_simulation_runs_and_submits() -> None:
    """Covers R-SBX-2 and R-SBX-7."""
    res = run(
        """
        import photonsim as ps, simagent_io
        r = ps.simulate(ps.Slab([ps.Layer("lead", 2.0)]), 1.0, 20_000, seed=1)
        print("done")
        simagent_io.submit(r.transmitted, result=r)
        """
    )
    assert res.ok, res.stderr
    value = answer(res)
    assert isinstance(value, float)
    assert 0.0 < value < 1.0
    assert res.result_json is not None
    assert res.result_json["data"]["result"]["n_photons"] == 20_000
    assert res.stdout.strip() == "done"


def test_matplotlib_works_headless() -> None:
    res = run(
        """
        import matplotlib.pyplot as plt, simagent_io
        plt.plot([1, 2], [3, 4])
        plt.savefig("/out/plot.png")
        with open("/out/notes.txt", "w") as fh:
            fh.write("not returned")
        simagent_io.submit("ok")
        """
    )
    assert res.ok, res.stderr
    assert set(res.files) == {"plot.png"}
    assert base64.b64decode(res.files["plot.png"]).startswith(b"\x89PNG")


def test_exit_zero_without_submit_is_failure() -> None:
    """Covers R-SBX-7."""
    res = run("print('forgot to submit')\n")
    assert res.exit_code == 0
    assert not res.ok
    assert "no result submitted" in (res.failure or "")


def test_exception_reports_traceback() -> None:
    res = run("import photonsim as ps\nps.Layer('unobtainium', 1.0)\n")
    assert res.exit_code == 1
    assert "ValueError" in res.stderr
    assert "unknown material" in res.stderr


def test_network_is_blocked() -> None:
    """Covers R-SBX-3 (--network none)."""
    res = run(
        """
        import socket, simagent_io
        outcomes = []
        for host, port in [("1.1.1.1", 53), ("8.8.8.8", 443)]:
            try:
                socket.create_connection((host, port), timeout=3)
                outcomes.append("connected")
            except OSError as exc:
                outcomes.append(type(exc).__name__)
        try:
            socket.getaddrinfo("example.com", 80)
            outcomes.append("resolved")
        except OSError as exc:
            outcomes.append(type(exc).__name__)
        ifaces = [name for _, name in socket.if_nameindex()]
        simagent_io.submit(outcomes, ifaces=ifaces)
        """
    )
    outcomes = answer(res)
    assert isinstance(outcomes, list)
    assert "connected" not in outcomes
    assert "resolved" not in outcomes
    assert res.result_json is not None
    assert res.result_json["data"]["ifaces"] == ["lo"]


def test_host_environment_not_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers R-SBX-5."""
    secret = "sk-test-0123456789abcdef-should-never-leak"
    monkeypatch.setenv("GROQ_API_KEY", secret)
    monkeypatch.setenv("SIMAGENT_TEST_SECRET", secret)
    res = run(
        """
        import os, simagent_io
        env = dict(os.environ)
        with open("/proc/1/environ", "rb") as fh:
            pid1 = fh.read().decode(errors="replace")
        simagent_io.submit(sorted(env), env=env, pid1=pid1)
        """
    )
    assert res.ok, res.stderr
    blob = json.dumps(res.result_json) + res.stdout + res.stderr
    assert secret not in blob
    names = answer(res)
    assert isinstance(names, list)
    assert "GROQ_API_KEY" not in names
    assert "SIMAGENT_TEST_SECRET" not in names


def test_filesystem_is_read_only_except_tmp_and_out() -> None:
    """Covers R-SBX-3 (read-only root, writable /tmp and /out, script mounted read-only)."""
    res = run(
        """
        import simagent_io
        results = {}
        paths = ["/etc/evil", "/evil", "/usr/evil", "/sandbox/evil", "/sandbox/script.py",
                 "/opt/simagent/launch.py", "/tmp/ok", "/out/ok"]
        for path in paths:
            try:
                with open(path, "a") as fh:
                    fh.write("x")
                results[path] = "written"
            except OSError as exc:
                results[path] = type(exc).__name__
        simagent_io.submit(results)
        """
    )
    results = answer(res)
    assert isinstance(results, dict)
    assert results.pop("/tmp/ok") == "written"
    assert results.pop("/out/ok") == "written"
    assert all(v != "written" for v in results.values()), results


def test_tmp_is_size_limited() -> None:
    """Covers R-SBX-3 (size-limited /tmp)."""
    res = run(
        """
        import simagent_io
        written = 0
        try:
            with open("/tmp/big", "wb") as fh:
                for _ in range(200):
                    fh.write(b"x" * 1024 * 1024)
                    fh.flush()
                    written += 1
        except OSError:
            pass
        simagent_io.submit(written)
        """,
        limits=SandboxLimits(tmp_mb=16),
    )
    written = answer(res)
    assert isinstance(written, int)
    assert written <= 16


def test_runs_as_non_root_without_capabilities() -> None:
    """Covers R-SBX-3 (non-root, --cap-drop ALL, no-new-privileges)."""
    res = run(
        """
        import os, simagent_io
        with open("/proc/self/status") as fh:
            status = fh.read().splitlines()
        fields = dict(line.split(":", 1) for line in status if ":" in line)
        simagent_io.submit(os.getuid(), gid=os.getgid(), cap_eff=fields["CapEff"].strip(),
                           no_new_privs=fields["NoNewPrivs"].strip())
        """
    )
    assert answer(res) == 10001
    assert res.result_json is not None
    data = res.result_json["data"]
    assert data["gid"] == 10001
    assert int(data["cap_eff"], 16) == 0
    assert data["no_new_privs"] == "1"


def test_timeout_kills_container() -> None:
    """Covers R-SBX-4."""
    res = run("while True:\n    pass\n", timeout_s=3)
    assert res.timed_out
    assert not res.ok
    assert res.duration_s < 30
    exe = docker_executable()
    assert exe is not None
    ps = subprocess.run(
        [exe, "ps", "-a", "--filter", "name=simagent-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert ps.stdout.strip() == ""


def test_memory_limit_triggers() -> None:
    """Covers R-SBX-3 (memory limit)."""
    res = run(
        """
        blocks = []
        for _ in range(64):
            blocks.append(bytearray(64 * 1024 * 1024))
        import simagent_io
        simagent_io.submit("allocated 4 GB")
        """,
        limits=SandboxLimits(memory_mb=256),
    )
    assert not res.ok
    assert res.exit_code != 0


def test_fork_bomb_contained_by_pid_limit() -> None:
    """Covers R-SBX-3 (PID limit)."""
    res = run(
        """
        import os, time, simagent_io
        started = 0
        for _ in range(500):
            try:
                pid = os.fork()
            except OSError:
                continue
            if pid == 0:
                time.sleep(5)
                os._exit(0)
            started += 1
        simagent_io.submit(started)
        """,
        timeout_s=60,
    )
    started = answer(res)
    assert isinstance(started, int)
    assert started < 64


def test_output_is_capped() -> None:
    """Covers R-SBX-6."""
    res = run("import sys\nprint('x' * 200_000)\nprint('LAST', file=sys.stderr)\n")
    assert len(res.stdout) < 21_000
    assert "truncated" in res.stdout
    assert "LAST" in res.stderr


MALICIOUS = """\
import os, socket, subprocess, simagent_io
report = {}
try:
    socket.create_connection(("1.1.1.1", 80), timeout=3)
    report["network"] = "open"
except OSError:
    report["network"] = "blocked"
try:
    with open("/etc/passwd", "a") as fh:
        fh.write("pwned")
    report["write_etc"] = "written"
except OSError:
    report["write_etc"] = "blocked"
try:
    with open("/sandbox/payload.sh", "w") as fh:
        fh.write("echo pwned")
    report["write_mount"] = "written"
except OSError:
    report["write_mount"] = "blocked"
try:
    out = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    report["uid"] = out
except OSError as exc:
    report["uid"] = type(exc).__name__
report["host_paths_visible"] = any(os.path.exists(p) for p in ["/host", "/c/Users", "/mnt/c"])
simagent_io.submit(report)
"""


def test_malicious_script_contained_with_policy_disabled() -> None:
    """Covers R-POL-5: the policy would reject this, and the sandbox contains it anyway."""
    assert not check(MALICIOUS).ok
    res = DockerRunner().run(MALICIOUS, timeout_s=30)
    report = answer(res)
    assert report == {
        "network": "blocked",
        "write_etc": "blocked",
        "write_mount": "blocked",
        "uid": "10001",
        "host_paths_visible": False,
    }
