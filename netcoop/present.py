"""Live-demo tooling (T10): preflight, scripted presentation, fallback snapshots.

    python tasks.py preflight            # red/green checks, non-zero exit on any failure
    python tasks.py present [--port N]   # scripted 8-step run, Enter between steps
    python tasks.py snapshots            # regenerate demo_snapshots/ (fallback if the live run fails)

Fully offline: everything is on 127.0.0.1, the LLM is forced off, and no step needs Wi-Fi or internet.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCEN = ROOT / "data" / "scenarios"
AGENT_JS = ROOT / "external_agents" / "wireless_agent" / "server.js"
SNAP_DIR = ROOT / "demo_snapshots"
DEFAULT_PORT = int(os.environ.get("NETCOOP_AGENT_PORT", "8765"))

if os.name == "nt":  # enable ANSI colors in Windows consoles
    os.system("")
TTY = sys.stdout.isatty()
COLOR = TTY and os.environ.get("NO_COLOR") is None


def set_color(on: bool) -> None:
    global COLOR
    COLOR = on


def c(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if COLOR else s


def ok(s: str) -> str:
    return c(s, "32;1")


def bad(s: str) -> str:
    return c(s, "31;1")


def dim(s: str) -> str:
    return c(s, "2")


# ---------------------------------------------------------------------------- wireless_agent process control

def _agent_pids(port: int) -> list[int]:
    """PIDs of OUR wireless_agent processes serving `port` (matched on the command line, never by name alone)."""
    pids: list[int] = []
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Select-Object ProcessId,CommandLine | ConvertTo-Json"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            rows = json.loads(out) if out else []
            rows = rows if isinstance(rows, list) else [rows]
            procs = [(int(r["ProcessId"]), r.get("CommandLine") or "") for r in rows]
        else:
            out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=10).stdout
            procs = [(int(line.split(None, 1)[0]), line.split(None, 1)[1]) for line in out.splitlines() if line.strip()]
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    for pid, cmd in procs:
        if "wireless_agent" not in cmd.replace("\\", "/") or "server.js" not in cmd:
            continue
        m = re.search(r"--port\s+(\d+)", cmd)
        if (int(m.group(1)) if m else 8765) == port and pid != os.getpid():
            pids.append(pid)
    return pids


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def kill_stale_agent(port: int) -> list[int]:
    pids = _agent_pids(port)
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
            else:
                os.kill(pid, 15)
        except OSError:
            pass
    for _ in range(50):
        if port_free(port):
            break
        time.sleep(0.1)
    return pids


class Agent:
    def __init__(self, port: int):
        self.port = port
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> bool:
        node = shutil.which("node")
        if not node:
            return False
        self.proc = subprocess.Popen([node, str(AGENT_JS), "--port", str(self.port)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.url + "/healthz", timeout=0.3)
                return True
            except OSError:
                time.sleep(0.05)
        return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def config_for_port(port: int):
    from netcoop.config import load_config, thaw

    cfg = load_config()
    agents = thaw(cfg.agents)
    agents["external"][0]["base_url"] = f"http://127.0.0.1:{port}"
    return cfg.with_overrides(agents=agents)


# ---------------------------------------------------------------------------- scenario runner

def run_scenario(name: str, cfg: Any, runs: Path, incident_id: str) -> tuple[dict[str, Any], Path]:
    from netcoop.orchestrator.run import RunOptions, run_incident
    from netcoop.timeline import write_timeline

    data = (SCEN / name / "incident.json").read_bytes()
    res = run_incident(data, cfg, RunOptions(incident_id=incident_id, runs_dir=runs, external=True, store=False))
    tl = write_timeline(res.run_dir, res.run_dir / "timeline.html")
    return res.report, tl


EXPECT = {  # scenario -> (status, fault_type) expected in the scripted demo
    "congestion": ("diagnosed", "congestion"),
    "weak_wifi:off": ("insufficient_evidence", None),
    "weak_wifi:on": ("diagnosed", "weak_wifi"),
    "interop": ("diagnosed", "device_overload"),
    "normal": ("no_fault_detected", None),
    "interface_fault": ("diagnosed", "interface_fault"),
    "dns_failure": ("diagnosed", "dns_failure"),
    "dhcp_failure": ("diagnosed", "dhcp_failure"),
}


def summary(rep: dict[str, Any], *, predictions: bool = False, normalization: bool = False, blocked: bool = False) -> str:
    color = {"diagnosed": "32;1", "probable": "33;1", "insufficient_evidence": "35;1", "no_fault_detected": "36;1"}.get(
        rep["status"], "31;1")
    lines = [f"  {c(rep['status'], color)}  {rep['suspected_root_cause']}",
             f"  confidence {rep['confidence']:.2f} ({rep.get('confidence_category')})   "
             f"affected: {', '.join(rep['affected_devices']) or '-'}   sources: {', '.join(rep['evidence_sources']) or '-'}"]
    for e in rep["supporting_evidence"][:6]:
        lines.append(dim(f"    - {e['metric']:<22} {e['value']:>9g} {e.get('unit', ''):<5} {e.get('entity', ''):<18} {e['interpretation']}"))
    if rep.get("missing_signals"):
        lines.append(f"  missing signals: {', '.join(rep['missing_signals'][:6])}")
    if predictions:
        for p in rep.get("predictions", []):
            mark = ok("HIT ") if p["outcome"] == "hit" else (bad("MISS") if p["outcome"] == "miss" else p["outcome"])
            lines.append(f"    {p['prediction_id']} [{p['hypothesis']}] {p['signal']} expected {p['expected']} -> {mark}"
                         + (f" (observed {p['observed']:g})" if p.get("observed") is not None else ""))
    if normalization:
        ns = rep.get("normalization_summary", {})
        lines.append("  normalization: " + ", ".join(f"{k} {v}" for k, v in ns.items() if v))
        lines += [dim(f"    - {x}") for x in rep["limitations"] if "quarantined" in x or "converted" in x
                  or "inferred" in x or "upcast" in x][:6]
    if blocked:
        for b in rep.get("blocked_actions", []):
            lines.append("  " + bad("BLOCKED ") + b["reason"])
        lines += [f"  recommended: {a}" for a in rep["recommended_actions"][:3]]
    return "\n".join(lines)


def check_expect(key: str, rep: dict[str, Any]) -> bool:
    st, ft = EXPECT[key]
    return rep["status"] == st and (ft is None or rep.get("fault_type") == ft)


# ---------------------------------------------------------------------------- preflight

@dataclass
class Result:
    name: str
    passed: bool
    detail: str


def in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def lan_ip() -> str | None:
    """This machine's non-loopback IPv4 address, if any (a UDP connect sends no packets)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") or ip == "0.0.0.0" else ip
    except OSError:
        return None


def loopback_only(port: int) -> tuple[bool, str]:
    """True if `port` is NOT reachable on the LAN address (the listener is bound to 127.0.0.1 only)."""
    ip = lan_ip()
    if ip is None:
        return True, "no LAN interface (offline): loopback only by construction"
    with socket.socket() as s:
        s.settimeout(0.5)
        try:
            s.connect((ip, port))
        except OSError:
            return True, f"listens on 127.0.0.1 only (not reachable on {ip})"
    return False, f"REACHABLE on LAN address {ip}:{port}"


FINGERPRINT_DIRS = ("netcoop", "config", "data/scenarios", "external_agents/wireless_agent")


def _tracked_files(dirs: tuple[str, ...]) -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", *dirs], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout
        files = [ROOT / f for f in out.splitlines() if f.strip()]
    except (OSError, subprocess.SubprocessError):
        files = []
    if not files:
        files = [p for d in dirs for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return sorted(f for f in files if f.is_file())


def content_hash(dirs: tuple[str, ...]) -> str:
    """sha256 over tracked file contents, line endings normalized (same hash on Windows and Linux checkouts)."""
    import hashlib

    h = hashlib.sha256()
    for f in _tracked_files(dirs):
        h.update(f.relative_to(ROOT).as_posix().encode() + b"\0")
        h.update(f.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def fingerprint() -> dict[str, str]:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                                timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    return {"generated_from_commit": commit or "unknown", "source_hash": content_hash(FINGERPRINT_DIRS),
            "config_hash": content_hash(("config",))}


def preflight(port: int) -> int:
    os.environ["NETCOOP_LLM"] = "off"
    results: list[Result] = []

    def check(name: str, fn: Callable[[], tuple[bool, str]], warn_only: bool = False) -> bool:
        try:
            passed, detail = fn()
        except Exception as exc:  # noqa: BLE001
            passed, detail = False, f"{type(exc).__name__}: {str(exc)[:160]}"
        if warn_only and not passed:
            print(f"  {c('WARN', '33;1')}  {name:<38} {dim(detail)}")
            return passed
        results.append(Result(name, passed, detail))
        print(f"  {ok('PASS') if passed else bad('FAIL')}  {name:<38} {dim(detail)}")
        return passed

    print(c("NetCoop preflight", "1") + dim(f"  (port {port}, offline)"))
    check("Running inside the project .venv", lambda: (in_venv(), sys.prefix))
    cols = shutil.get_terminal_size((80, 24)).columns
    check("Terminal width >= 100 columns", lambda: (cols >= 100, f"{cols} columns (widen the window)"), warn_only=True)
    check("Python >= 3.11", lambda: (sys.version_info >= (3, 11), sys.version.split()[0]))

    def node_ver() -> tuple[bool, str]:
        node = shutil.which("node")
        if not node:
            return False, "node not on PATH"
        v = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        return int(v.lstrip("v").split(".")[0]) >= 18, v
    check("Node >= 18", node_ver)

    def deps() -> tuple[bool, str]:
        import importlib
        mods = ["pydantic", "yaml", "netcoop", "conformance.kit"]
        missing = [m for m in mods if importlib.util.find_spec(m.split(".")[0]) is None]
        for m in mods:
            importlib.import_module(m)
        return not missing, "pydantic, pyyaml, netcoop, conformance kit importable"
    check("Python dependencies", deps)
    check("LLM off (no API / model needed)", lambda: (os.environ.get("NETCOOP_LLM", "off") == "off", "NETCOOP_LLM=off"))

    def offline() -> tuple[bool, str]:
        from netcoop.config import load_config
        urls = [s["base_url"] for s in load_config().agents.get("external", ())]
        loop = all(re.match(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?/?$", u) for u in urls)
        return loop, "allowlist is loopback only: " + ", ".join(urls)
    check("No network needed", offline)

    def stale() -> tuple[bool, str]:
        killed = kill_stale_agent(port)
        return port_free(port), (f"killed stale agent pid(s) {killed}; " if killed else "") + f"port {port} free"
    check(f"Port {port} free (stale agent cleared)", stale)

    agent = Agent(port)
    try:
        def start() -> tuple[bool, str]:
            started = agent.start()
            return started, f"wifi-probe up on {agent.url}" if started else "agent did not start"
        if check("wireless_agent starts", start):
            def conf() -> tuple[bool, str]:
                from conformance.kit import Kit
                cs = Kit(agent.url).run()
                return all(x.passed for x in cs), f"{sum(x.passed for x in cs)}/{len(cs)} checks"
            check("Conformance kit vs wireless_agent", conf)
            check("wireless_agent bound to 127.0.0.1 only", lambda: loopback_only(port))

            def scenarios() -> tuple[bool, str]:
                import tempfile
                cfg_on = config_for_port(port)
                with tempfile.TemporaryDirectory() as tmp:
                    bad_ones = []
                    for i, name in enumerate(["congestion", "weak_wifi", "interface_fault", "dns_failure", "dhcp_failure",
                                              "interop", "normal"]):
                        rep, _ = run_scenario(name, cfg_on, Path(tmp), f"INC-PREF{i:04d}")
                        key = "weak_wifi:on" if name == "weak_wifi" else name
                        if not check_expect(key, rep):
                            bad_ones.append(f"{name}={rep['status']}")
                return not bad_ones, "all 7 scenarios as expected" if not bad_ones else "; ".join(bad_ones)
            check("All scenarios (agent joined)", scenarios)
    finally:
        agent.stop()

    def stopped() -> tuple[bool, str]:
        for _ in range(50):
            if port_free(port):
                return True, "agent stopped, port released"
            time.sleep(0.1)
        return False, "port still busy after stop"
    check("wireless_agent stops cleanly", stopped)

    def offline_wifi() -> tuple[bool, str]:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rep, _ = run_scenario("weak_wifi", config_for_port(port), Path(tmp), "INC-PREFOFF1")
        return check_expect("weak_wifi:off", rep), f"Wi-Fi without agent -> {rep['status']}"
    check("Hot-plug baseline (agent absent)", offline_wifi)

    def snaps() -> tuple[bool, str]:
        have = [step for step, _ in STEPS if (SNAP_DIR / step).is_dir() and any((SNAP_DIR / step).iterdir())]
        return len(have) == len(STEPS), f"{len(have)}/{len(STEPS)} step folders in demo_snapshots/"
    check("Fallback snapshots present", snaps)

    def fresh() -> tuple[bool, str]:
        meta = SNAP_DIR / "meta.json"
        if not meta.exists():
            return False, "demo_snapshots/meta.json missing: run `python tasks.py snapshots`"
        m = json.loads(meta.read_text(encoding="utf-8"))
        cur = fingerprint()
        stale = [k for k in ("source_hash", "config_hash") if m.get(k) != cur[k]]
        if stale:
            return False, f"{', '.join(stale)} changed since the snapshots: run `python tasks.py snapshots`"
        return True, f"match current code + config (generated from {m.get('generated_from_commit')})"
    check("Snapshots fresh (code + config hash)", fresh)
    failed = [r for r in results if not r.passed]
    print()
    print(ok(f"PREFLIGHT OK: {len(results)}/{len(results)} checks passed") if not failed
          else bad(f"PREFLIGHT FAILED: {len(failed)} of {len(results)} checks failed"))
    return 0 if not failed else 1


# ---------------------------------------------------------------------------- scripted presentation

STEPS = [
    ("01_congestion", "Congestion: agents collaborate; predictions logged BEFORE evidence is requested"),
    ("02_wifi_insufficient", "Weak Wi-Fi without the external agent -> honest insufficient_evidence"),
    ("03_start_agent", "Hot-plug: start the external wireless_agent (Node.js, dialect v0.9)"),
    ("04_conformance", "Conformance kit against the newly joined agent"),
    ("05_wifi_diagnosed", "Same Wi-Fi incident, agent joined -> diagnosed at AP_H3"),
    ("06_chaos_input", "Chaos input: v0.9 block, renamed fields, seconds, fractions, mangled IDs, garbage"),
    ("07_policy_blocked", "Policy: reboot of a core switch blocked by R1 (class hours)"),
    ("08_normal", "Normal network -> no_fault_detected"),
]


def present(port: int, *, auto: bool = False, out: Path | None = None, with_judge: bool = False, delay: float = 0.0,
            open_browser: bool = False) -> int:
    os.environ["NETCOOP_LLM"] = "off"
    runs = (ROOT / "runs" / "present") if out is None else out / "_runs"
    if runs.exists():
        shutil.rmtree(runs, ignore_errors=True)
    cfg = config_for_port(port)
    killed = kill_stale_agent(port)
    if killed:
        print(dim(f"(stopped stale wireless_agent pid(s) {killed} on port {port})"))
    if not port_free(port):
        print(bad(f"port {port} is busy with something that is not our agent; use --port"))
        return 2
    agent = Agent(port)
    reports: dict[str, dict[str, Any]] = {}
    failures: list[str] = []

    def pause() -> None:
        if auto:
            if delay > 0:
                time.sleep(delay)
            return
        if not auto:
            try:
                input(dim("\n  [Enter] next step "))
            except EOFError:
                pass

    def save(step: str, rep: dict[str, Any] | None, tl: Path | None, extra: str | None = None) -> None:
        if out is None:
            return
        d = out / step
        d.mkdir(parents=True, exist_ok=True)
        if rep is not None:
            (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        if tl is not None:
            shutil.copyfile(tl, d / "timeline.html")
        if extra is not None:
            (d / "output.txt").write_text(extra, encoding="utf-8")

    try:
        for i, (step, title) in enumerate(STEPS, 1):
            print("\n" + c(f"[{i}/8] {title}", "1;34"))
            rep = tl = None
            text = None
            if step == "01_congestion":
                rep, tl = run_scenario("congestion", cfg, runs, "INC-DEMO0001")
                print(summary(rep, predictions=True))
                reports["congestion"] = rep
                if not check_expect("congestion", rep):
                    failures.append(step)
            elif step == "02_wifi_insufficient":
                rep, tl = run_scenario("weak_wifi", cfg, runs, "INC-DEMO0002")
                print(summary(rep))
                if not check_expect("weak_wifi:off", rep):
                    failures.append(step)
            elif step == "03_start_agent":
                started = agent.start()
                card = json.loads(urllib.request.urlopen(agent.url + "/.well-known/agent-card.json", timeout=2).read()) \
                    if started else {}
                text = (f"wireless_agent {'started' if started else 'FAILED TO START'} on {agent.url}\n"
                        f"card: {card.get('name')} v{card.get('version')}  skills: {[s['id'] for s in card.get('skills', [])]}\n"
                        "It speaks dialect 0.9: {\"ver\":\"0.9\",\"obs\":[{\"ap\":\"ap-h3\",\"signal\":-78,\"noise_margin\":9,\"retx\":0.22,...}]}")
                print("  " + text.replace("\n", "\n  "))
                if not started:
                    failures.append(step)
            elif step == "04_conformance":
                from conformance.kit import Kit
                cs = Kit(agent.url).run()
                text = "\n".join(f"{'PASS' if x.passed else 'FAIL'}  {x.name:<42} {x.detail}" for x in cs)
                for x in cs:
                    print(f"  {ok('PASS') if x.passed else bad('FAIL')}  {x.name:<42} {dim(x.detail)}")
                print(f"  conformance: {sum(x.passed for x in cs)}/{len(cs)}")
                if not all(x.passed for x in cs):
                    failures.append(step)
            elif step == "05_wifi_diagnosed":
                rep, tl = run_scenario("weak_wifi", cfg, runs, "INC-DEMO0005")
                print(summary(rep, predictions=True))
                if not check_expect("weak_wifi:on", rep):
                    failures.append(step)
            elif step == "06_chaos_input":
                rep, tl = run_scenario("interop", cfg, runs, "INC-DEMO0006")
                print(summary(rep, normalization=True))
                if not check_expect("interop", rep):
                    failures.append(step)
            elif step == "07_policy_blocked":
                rep = reports["congestion"]
                tl = runs / "INC-DEMO0001" / "timeline.html"
                print(f"  {rep['suspected_root_cause']}")
                print(summary(rep, blocked=True).split("\n", 2)[-1])
                if not any(b["rule_id"] == "R1" for b in rep.get("blocked_actions", [])):
                    failures.append(step)
            elif step == "08_normal":
                rep, tl = run_scenario("normal", cfg, runs, "INC-DEMO0008")
                print(summary(rep))
                if not check_expect("normal", rep):
                    failures.append(step)
            if tl is not None:
                print(dim(f"  timeline: {tl}"))
                if open_browser and out is None:
                    import webbrowser
                    try:
                        webbrowser.open(Path(tl).resolve().as_uri())
                    except Exception:  # noqa: BLE001 - optional; never break the demo
                        print(dim("  (could not open a browser; the file path is above)"))
            save(step, rep, tl, text)
            if i < len(STEPS):
                pause()
        if with_judge:  # optional step 9: a judge picks the organizer label and seed
            pause()
            print("\n" + c("[9/9] Judge mode: you pick an organizer label and a seed", "1;34"))
            fault, seed = "random", "random"
            if not auto:
                try:
                    fault = input(f"  label ({'/'.join(ORGANIZER_LABELS)}/random) [random]: ").strip() or "random"
                    seed = input("  seed (number/random) [random]: ").strip() or "random"
                except EOFError:
                    pass
            if judge(fault, seed, runs) != 0:
                failures.append("09_judge")
    finally:
        agent.stop()
    print()
    if failures:
        print(bad(f"{len(failures)} step(s) did not match the script: {', '.join(failures)}"))
        print(dim("  fallback: open demo_snapshots/<step>/timeline.html"))
        return 1
    print(ok(f"All {len(STEPS) + (1 if with_judge else 0)} steps matched the script. Measured, not claimed."))
    return 0


# ---------------------------------------------------------------------------- judge mode (U6)

ORGANIZER_LABELS = ("normal", "latency_spike", "hardware_failure")
EXPECTED_FOR_LABEL = {"normal": ("no_fault_detected", None), "latency_spike": ("diagnosed", "latency_spike"),
                      "hardware_failure": ("diagnosed", "hardware_failure")}


def judge(fault: str = "random", seed: str | int = "random", runs: Path | None = None) -> int:
    """Raw organizer generator -> full pipeline -> summary + timeline. A judge picks the label and seed."""
    import random as _random

    from eval.organizer_check import load_generator
    from netcoop.config import load_config, thaw

    os.environ["NETCOOP_LLM"] = "off"
    pick = _random.SystemRandom()
    label = pick.choice(ORGANIZER_LABELS) if fault == "random" else fault
    if label not in ORGANIZER_LABELS:
        print(bad(f"unknown organizer label {label!r}; choose one of {', '.join(ORGANIZER_LABELS)} or random"))
        return 2
    s = pick.randrange(1_000_000) if str(seed) == "random" else int(seed)
    _random.seed(s)
    rec = load_generator()(label)  # exactly what the organizer's generator emits, no preprocessing
    print(c(f"Judge mode: organizer generator, label={label}, seed={s}", "1;34"))
    print(dim("  raw record: " + json.dumps(rec)))
    base = load_config()
    agents = thaw(base.agents)
    agents["external"] = []  # organizer data has no Wi-Fi telemetry
    cfg = base.with_overrides(agents=agents)
    rep, tl = run_scenario_bytes(json.dumps(rec).encode(), cfg, runs or ROOT / "runs" / "judge", f"INC-JUDGE{s % 10000:04d}")
    print(summary(rep))
    st, ft = EXPECTED_FOR_LABEL[label]
    match = rep["status"] == st and (ft is None or rep.get("fault_type") == ft)
    print(("  " + ok("MATCHES") if match else "  " + bad("DIFFERS FROM")) +
          f" the documented mapping {label} -> {ft or st} (data/generator/SCHEMA.md)")
    print(dim(f"  timeline: {tl}"))
    return 0 if match else 1


def run_scenario_bytes(data: bytes, cfg: Any, runs: Path, incident_id: str) -> tuple[dict[str, Any], Path]:
    from netcoop.orchestrator.run import RunOptions, run_incident
    from netcoop.timeline import write_timeline

    res = run_incident(data, cfg, RunOptions(incident_id=incident_id, runs_dir=runs, external=False, store=False))
    return res.report, write_timeline(res.run_dir, res.run_dir / "timeline.html")


def snapshots(port: int) -> int:
    if SNAP_DIR.exists():
        shutil.rmtree(SNAP_DIR)
    rc = present(port, auto=True, out=SNAP_DIR)
    (SNAP_DIR / "meta.json").write_text(json.dumps(fingerprint(), indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(SNAP_DIR / "_runs", ignore_errors=True)
    (SNAP_DIR / "README.md").write_text(
        "# Demo snapshots (fallback)\n\nGenerated by `python tasks.py snapshots`. One folder per step of "
        "`python tasks.py present`: `report.json` and a static `timeline.html` (open it in any browser, works offline). "
        "Step 3/4 save the agent card and the conformance output as `output.txt`.\n", encoding="utf-8")
    print(f"snapshots written to {SNAP_DIR}")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tasks.py")
    ap.add_argument("cmd", choices=["preflight", "present", "snapshots", "judge"])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--auto", action="store_true", help="present without waiting for Enter")
    ap.add_argument("--judge", action="store_true", help="present: add optional step 9 (judge mode)")
    ap.add_argument("--fault", default="random", help="judge: organizer label or random")
    ap.add_argument("--seed", default="random", help="judge: integer seed or random")
    ap.add_argument("--delay", type=float, default=0.0, help="present --auto: seconds to wait between steps")
    ap.add_argument("--no-color", action="store_true", help="plain text output (projectors)")
    ap.add_argument("--open", action="store_true", help="present: open each step's timeline in the browser")
    a = ap.parse_args(argv)
    if a.no_color:
        set_color(False)
    if a.cmd == "preflight":
        return preflight(a.port)
    if a.cmd == "present":
        return present(a.port, auto=a.auto, with_judge=a.judge, delay=a.delay, open_browser=a.open)
    if a.cmd == "judge":
        return judge(a.fault, a.seed)
    return snapshots(a.port)


if __name__ == "__main__":
    raise SystemExit(main())
