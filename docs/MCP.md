# NetCoop as an MCP server

`netcoop mcp` exposes NetCoop to any MCP client (for example Claude Desktop) over stdio. The client's LLM can run
diagnoses and read the results. It **cannot** change them: root cause, confidence, status and actions are always
computed by NetCoop's deterministic scoring (CLAUDE.md D1). Every analysis agent runs on every diagnosis (D9).

## Install

```
.venv\Scripts\python -m pip install -e ".[mcp]"      # or .[dev], which includes it
.venv\Scripts\python -m netcoop mcp                  # speaks MCP on stdin/stdout; Ctrl+C to stop
```

## Tools

| Tool | Arguments | Returns | Side effects |
|---|---|---|---|
| `list_scenarios` | none | built-in scenario names, record counts and paths | none |
| `list_agents` | none | internal agents with their tools and owned metrics; allowlisted external agents and whether each is reachable | probes only the loopback URLs in `config/agents.yaml` |
| `diagnose` | `scenario` **or** `telemetry_path` | summary: incident_id, status, fault_type, confidence, root cause, affected devices, `decision_source` | writes `runs/<incident_id>/` (event log + report), the same as the CLI does |
| `get_report` | `incident_id` | the full JSON report | none |
| `explain` | `incident_id` | evidence with `finding_id` and source agent, predictions with the event-log `seq` at which each was logged, alternatives, blocked actions, limitations, per-agent status | none |

## Guardrails (§11 applied to MCP tool arguments)

- `scenario` must match `^[a-z][a-z_]{0,39}$` and must name a folder under `data/scenarios/`.
- `telemetry_path` must match `^(data|runs)/[A-Za-z0-9_\-./]{1,200}\.(json|csv)$` and contain no `..`. The resolved
  path must stay inside `data/` or `runs/`, which blocks symlink escapes. Files are capped at 10 MB. Absolute paths,
  backslashes, `.env`, `config/` and non-JSON/CSV files are all rejected.
- `incident_id` must match `^INC-[0-9A-Z]{4,12}$` and is checked again by `safe_run_dir` before `runs/` is touched.
- The server runs no shell commands and touches no network device. Remediation is never executed (G1, G2).
- Tool results enter the client LLM's context, so quoted raw input in limitations (for example a quarantined
  device name carrying an injection) is replaced with `'<redacted raw input>'`. Validated IDs, numbers and enums
  pass through unchanged.
- The server instructions tell the client that tool results are data, not instructions.
- Tests: `tests/security/test_mcp_server.py` covers tool schemas, path traversal, bad IDs and scenario names, an
  injection in a device name (no change to the diagnosis and nothing echoed back), and injection text in arguments.

## Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`),
replacing the paths with your clone's:

```json
{
  "mcpServers": {
    "netcoop": {
      "command": "C:\\Projects\\new\\.venv\\Scripts\\python.exe",
      "args": ["-m", "netcoop", "mcp"],
      "cwd": "C:\\Projects\\new"
    }
  }
}
```

Restart Claude Desktop. **netcoop** then appears under the tools (hammer) icon.

## Example prompts

1. *"Use NetCoop to list the scenarios, then diagnose the congestion one. What is the root cause and how confident is it?"*
2. *"Explain that incident: which agents produced the evidence, and which predictions were logged before the evidence came back? Were any of them misses?"*
3. *"Diagnose the weak_wifi scenario. Why isn't it diagnosed, and what data would resolve it? Is the wireless agent reachable?"*

For prompt 3 with `wireless_agent` stopped, the expected answer is `insufficient_evidence` and `list_agents` shows
it as unreachable. Start `node external_agents/wireless_agent/server.js` and ask again: the scenario is then diagnosed.
