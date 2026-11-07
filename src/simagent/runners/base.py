"""Runner interface and RunResult (R-SBX-1).

Generated code is only ever executed through a ``Runner``. Limits are fixed by the caller's
configuration (never by the model): see ``SandboxLimits``.
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import IO, Any

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_OUTPUT_CAP = 20_000
MAX_RESULT_BYTES = 1_000_000
RESULT_MARKER = "<<<SIMAGENT_RESULT:"


class RunnerUnavailableError(RuntimeError):
    """The runner cannot be used (e.g. Docker missing or the sandbox image not built)."""


@dataclass(frozen=True)
class SandboxLimits:
    """Resource limits for one run. Set by configuration, never by the model (R-AG-8)."""

    memory_mb: int = 512
    cpus: float = 1.0
    pids: int = 64
    tmp_mb: int = 64
    out_mb: int = 16
    output_cap: int = DEFAULT_OUTPUT_CAP


@dataclass(frozen=True)
class RunResult:
    """Outcome of one run (R-SBX-1)."""

    exit_code: int
    stdout: str
    stderr: str
    result_json: dict[str, Any] | None
    timed_out: bool
    duration_s: float
    result_error: str | None = None
    runner: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the script exited 0, did not time out and submitted a result (R-SBX-7)."""
        return self.exit_code == 0 and not self.timed_out and self.result_json is not None

    @property
    def failure(self) -> str | None:
        """Short reason the run failed, or None when ``ok``."""
        if self.timed_out:
            return "timed out"
        if self.exit_code != 0:
            return f"exit code {self.exit_code}"
        if self.result_error:
            return self.result_error
        if self.result_json is None:
            return "no result submitted (call simagent_io.submit(answer, **data))"
        return None


class Runner(ABC):
    """Executes a script and reports its outcome."""

    name: str = "runner"

    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()

    @abstractmethod
    def run(self, code: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> RunResult:
        """Run ``code`` with a wall-clock limit of ``timeout_s`` seconds."""


def cap_text(text: str, cap: int) -> str:
    """Keep the last ``cap`` characters of ``text`` (R-SBX-6), noting what was dropped."""
    if len(text) <= cap:
        return text
    dropped = len(text) - cap
    return f"[... {dropped} characters truncated ...]\n" + text[-cap:]


class TailReader:
    """Reads a binary stream on a thread, keeping only the last ``limit`` bytes."""

    def __init__(self, stream: IO[bytes], limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self.total = 0
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while True:
            chunk = self._stream.read(65536)
            if not chunk:
                break
            self.total += len(chunk)
            self._chunks.append(chunk)
            self._size += len(chunk)
            while self._size - len(self._chunks[0]) >= self._limit:
                self._size -= len(self._chunks.popleft())

    def text(self, timeout: float = 10.0) -> str:
        """Wait for the stream to close and return the kept tail, decoded as UTF-8."""
        self._thread.join(timeout)
        data = b"".join(self._chunks)[-self._limit :]
        text = data.decode("utf-8", errors="replace")
        if self.total > len(data):
            return f"[... {self.total - len(data)} bytes truncated ...]\n" + text
        return text


def split_result(stdout: str, nonce: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """Split launcher output into (script stdout, result dict, result error)."""
    marker = f"\n{RESULT_MARKER}{nonce}>>>\n"
    stdout = stdout.replace("\r\n", "\n")
    idx = stdout.rfind(marker)
    if idx < 0:
        return stdout, None, None
    body = stdout[idx + len(marker) :]
    before = stdout[:idx]
    return before, *parse_result(body)


def parse_result(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse result.json content; returns (result, error)."""
    if len(text.encode("utf-8")) > MAX_RESULT_BYTES:
        return None, f"result.json is larger than {MAX_RESULT_BYTES} bytes"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"result.json is not valid JSON: {exc.msg}"
    if isinstance(data, dict) and "__too_large__" in data:
        return None, f"result.json is larger than {MAX_RESULT_BYTES} bytes"
    if not isinstance(data, dict) or "answer" not in data:
        return None, "result.json must be an object with an 'answer' key (use simagent_io.submit)"
    return data, None
