# MCP client session (recorded)

Recorded by `scripts/mcp_demo.py` on 2026-11-07 08:54 UTC: an MCP client launches `simagent mcp` over stdio and calls the tools. Responses are shown as received (durations rounded).

## `list_tools`

Response:

```json
[
  "describe_simulator",
  "run_simulation_script",
  "solve"
]
```

## `run_simulation_script`

Client-written script:

```python
import photonsim as ps
import simagent_io

curve = ps.sweep(lambda t: ps.Slab([ps.Layer("lead", t)]), [1.0, 2.0, 4.0], 1.0, 20000, seed=1)
simagent_io.submit([[t, r.transmitted] for t, r in curve])
```

Response:

```json
{
  "ok": true,
  "failure": null,
  "policy_violations": [],
  "run": {
    "runner": "docker",
    "exit_code": 0,
    "timed_out": false,
    "duration_s": 1.7,
    "result": {
      "answer": [
        [
          1.0,
          0.52045
        ],
        [
          2.0,
          0.2608
        ],
        [
          4.0,
          0.06415
        ]
      ],
      "data": {}
    },
    "result_error": null,
    "stdout": "",
    "stderr": "",
    "files": {},
    "warnings": []
  }
}
```

## `run_simulation_script`

Client-written script:

```python
import matplotlib
matplotlib.os.system("cat /etc/passwd")
```

Response:

```json
{
  "ok": false,
  "failure": "policy violation",
  "policy_violations": [
    "line 2: `.os` is not allowed: modules such as os may not be reached through another module's attributes",
    "line 2: `.system` is not allowed (file, process or native access)"
  ],
  "run": null
}
```
