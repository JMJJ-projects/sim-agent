# Using simagent from an MCP client

`simagent mcp` starts an MCP server on stdio (official `mcp` Python SDK 2.x). Any MCP client can
launch it as a subprocess.

## Tools

| Tool | Arguments | What it does |
|---|---|---|
| `describe_simulator` | none | photonsim API reference, the `simagent_io.submit` result contract, and the sandbox limits |
| `run_simulation_script` | `code` | static policy check, then a run in the Docker sandbox; returns exit code, capped stdout/stderr, the submitted result and PNGs from `/out` (base64) |
| `solve` | `request`, `max_attempts` (default 4, max 10) | the full agent: writes a script with the server's configured model, runs it, repairs it from the error output |

Timeout, memory/CPU/PID limits and the runner are fixed by the server configuration. No tool
accepts them, and extra arguments such as `timeout_s` are dropped before the tool runs. The
policy and sandbox are the same as for the CLI.

Two ways to use it:

- **The client's own model writes the scripts:** call `describe_simulator`, then
  `run_simulation_script` with your code. Only the sandbox and policy are used.
- **The server's agent does the work:** call `solve` with a plain-language request. It uses the
  provider configured for the server (e.g. a local Ollama model), not the client's model.

## Prerequisites

1. `pip install -e ".[ollama]"` in the project's virtual environment.
2. Docker running and the sandbox image built: `docker build -f sandbox/Dockerfile -t simagent-sandbox .`
3. `simagent doctor` shows docker and the sandbox image as ok. For `solve` with Ollama, the
   model must be pulled (`ollama pull qwen2.5-coder:3b`).

## Claude Desktop

Edit `claude_desktop_config.json` (Windows: `%APPDATA%\Claude\claude_desktop_config.json`;
macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`) and restart Claude
Desktop. Replace `<repo>` with the absolute path of your clone:

```json
{
  "mcpServers": {
    "simagent": {
      "command": "<repo>\\.venv\\Scripts\\simagent.exe",
      "args": ["mcp"],
      "env": {
        "LLM_PROVIDER": "ollama",
        "LLM_MODEL": "qwen2.5-coder:3b",
        "SIMAGENT_RUNS_DIR": "<repo>\\runs"
      }
    }
  }
}
```

On macOS/Linux the command is `<repo>/.venv/bin/simagent`. Notes:

- `SIMAGENT_RUNS_DIR` should be absolute: the client starts the server in its own working
  directory, and artifacts of `solve` runs are written there.
- The server process needs `docker` on its `PATH`. If `run_simulation_script` reports
  "sandbox not available: docker CLI not found", add Docker's `bin` directory to `PATH` in the
  `env` block (Docker Desktop on Windows: `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`
  or `C:\Program Files\Docker\Docker\resources\bin`, depending on the install).
- API keys for hosted providers can be passed in `env` too; nothing else from the host
  environment reaches the sandbox.

## Claude Code

```bash
claude mcp add simagent -e LLM_PROVIDER=ollama -e LLM_MODEL=qwen2.5-coder:3b -- <repo>/.venv/Scripts/simagent.exe mcp
```

## Try it

Ask the client, for example: "Use the simagent tools to find the lead thickness, to the nearest
0.5 cm, at which fewer than 1 % of 1 MeV photons get through." A client model will typically
call `describe_simulator`, then either `solve` or `run_simulation_script` with its own sweep.

## Offline check

`simagent mcp --provider fake` starts the server with the scripted demo model (no API key, no
GPU); `solve` then replays the built-in buggy-then-fixed script. The test suite drives all tools
through an in-process MCP client (`tests/test_mcp.py`) and through a real stdio subprocess
(`tests/test_mcp_stdio.py`).
