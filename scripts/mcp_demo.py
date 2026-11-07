"""Record docs/mcp_demo.md: a real MCP client session with `simagent mcp` over stdio (R-MCP-3).

The client launches the server as a subprocess, lists the tools, then calls
run_simulation_script twice (a valid sweep and a script the policy rejects). The responses are
written exactly as received. Needs Docker and the sandbox image; no model is called.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]

SWEEP = """\
import photonsim as ps
import simagent_io

curve = ps.sweep(lambda t: ps.Slab([ps.Layer("lead", t)]), [1.0, 2.0, 4.0], 1.0, 20000, seed=1)
simagent_io.submit([[t, r.transmitted] for t, r in curve])
"""

BLOCKED = """\
import matplotlib
matplotlib.os.system("cat /etc/passwd")
"""


def _trim(report: dict[str, Any]) -> dict[str, Any]:
    run = report.get("run")
    if isinstance(run, dict):
        run = dict(run)
        run["duration_s"] = round(float(run["duration_s"]), 1)
        report = {**report, "run": run}
    return report


async def session() -> list[tuple[str, str, Any]]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from simagent.cli import app; app()", "mcp", "--provider", "fake"],
    )
    log: list[tuple[str, str, Any]] = []
    async with Client(params) as client:
        tools = await client.list_tools()
        log.append(("list_tools", "", [t.name for t in tools.tools]))
        for code in (SWEEP, BLOCKED):
            result = await client.call_tool("run_simulation_script", {"code": code})
            log.append(("run_simulation_script", code, _trim(json.loads(result.content[0].text))))
    return log


def main() -> int:
    log = anyio.run(session)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "# MCP client session (recorded)",
        "",
        f"Recorded by `scripts/mcp_demo.py` on {stamp}: an MCP client launches `simagent mcp` "
        "over stdio and calls the tools. Responses are shown as received (durations rounded).",
        "",
    ]
    for tool, code, response in log:
        out.append(f"## `{tool}`\n")
        if code:
            out.append("Client-written script:\n\n```python\n" + code.rstrip() + "\n```\n")
        out.append("Response:\n\n```json\n" + json.dumps(response, indent=2) + "\n```\n")
    path = ROOT / "docs" / "mcp_demo.md"
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
