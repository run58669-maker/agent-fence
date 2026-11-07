"""PreToolUse hook: killing processes by name is always blocked; killing by PID is allowed
only for PIDs listed in kill_allowlist.txt. Applies to the main thread and every subagent.

- Blocked: taskkill /IM|/FI; Stop-Process/spps/kill (PowerShell alias) with -Name or fed by a pipe;
  pkill/killall; kill fed by pgrep / ps|grep / xargs; wmic process ... delete|terminate;
  Win32_Process Terminate; .Kill() on an object.
- By PID: taskkill /PID n, Stop-Process -Id n, kill [-9] n -- every PID must be in kill_allowlist.txt.
- PID that is not a literal number ($pid etc.) -> blocked.
- Anything else / empty / parse failure -> exit 0 (allow).
Block = exit 2 + message on stderr (UTF-8).

kill_allowlist.txt: one PID per line, written by the orchestrating (main) session after it has
looked at the process; cleared after the kill.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _hookio import read_payload  # noqa: E402
except Exception:  # pragma: no cover
    def read_payload(caller="?"):
        import json
        try:
            return json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return {}

ALLOWLIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kill_allowlist.txt")
I = re.I


def deny(msg):
    try:
        sys.stderr.buffer.write(("[guard_kill] " + msg + "\n").encode("utf-8"))
        sys.stderr.flush()
    except Exception:
        pass
    sys.exit(2)


def load_allow():
    s = set()
    try:
        with open(ALLOWLIST, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.isdigit():
                    s.add(int(line))
    except Exception:
        pass
    return s


# ---- kill by name: scan the whole text (also covers nested powershell -Command "..." / bash -c '...') ----
NAME_KILL = [
    (re.compile(r"\btaskkill\b[^\n;|&]*?[/-](im|fi)\b", I), "taskkill /IM or /FI (kill by name)"),
    (re.compile(r"(?<![\w-])(pkill|killall)(?![\w-])", I), "pkill/killall (kill by name)"),
    (re.compile(r"(?<![\w-])(stop-process|spps)\b[^\n;|&]*?\s-(name|processname|n|inputobject)\b", I), "Stop-Process -Name (kill by name)"),
    (re.compile(r"(?<![\w-])kill\b[^\n;|&]*?\s-(name|processname|inputobject)\b", I), "kill -Name (kill by name)"),
    (re.compile(r"\|\s*(%\s*\{[^}]*)?(stop-process|spps)\b", I), "pipe into Stop-Process"),
    (re.compile(r"\|\s*kill\b", I), "pipe into kill"),
    (re.compile(r"\bxargs\b[^\n;|&]*\bkill\b", I), "xargs kill"),
    (re.compile(r"(\$\(|`)\s*(pgrep|pidof|ps\b|get-process|gps\b)", I), "kill fed by pgrep/ps subcommand"),
    (re.compile(r"\bpgrep\b[^\n]*\|[^\n]*\bkill\b", I), "pgrep | kill"),
    (re.compile(r"\bwmic\b[^\n]*\bprocess\b[^\n]*\b(delete|terminate)\b", I), "wmic process delete/terminate"),
    (re.compile(r"win32_process[^\n]*\bterminate\b", I), "Win32_Process Terminate"),
    (re.compile(r"\.kill\(\)", I), ".Kill() method (PID of the object cannot be verified)"),
]

SPLIT_STMT = re.compile(r"\|\||&&|[;\n&|]")
LEAD_STRIP = re.compile(r"^[\s\"'(`$]*(sudo\s+|exec\s+|command\s+|&\s*)*", I)


def check_pids(pids, where):
    if not pids:
        return
    allow = load_allow()
    for p in pids:
        if not p.isdigit():
            deny(f"{where}: PID '{p}' is not a literal number and cannot be checked; the main session must write the concrete PID to kill_allowlist.txt first")
        if int(p) not in allow:
            deny(f"PID {p} is not in kill_allowlist.txt; the main session must add it before killing")


def split_ids(s):
    return [x for x in re.split(r"[\s,]+", s.strip().strip("\"'()")) if x]


def check_stage(stage):
    st = LEAD_STRIP.sub("", stage).strip()
    if not st:
        return
    m = re.match(r"([\w.\-]+)\s*(.*)$", st, re.S)
    if not m:
        return
    cmd, rest = m.group(1).lower(), m.group(2)
    if cmd.endswith(".exe"):
        cmd = cmd[:-4]
    if cmd == "taskkill":
        pids = re.findall(r"[/-]pid\s+(\S+)", rest, I)
        check_pids([p.strip("\"'") for p in pids], "taskkill")
    elif cmd in ("stop-process", "spps"):
        pids = []
        for v in re.findall(r"-id\s+([^\s-][^-]*?)(?=\s+-|$)", rest, I):
            pids += split_ids(v)
        if not pids:
            first = re.match(r"([^\s-][^\s]*(?:\s*,\s*[^\s-][^\s]*)*)", rest.strip())
            if first:
                pids = split_ids(first.group(1))
        if not pids:
            deny("Stop-Process without a literal PID (-Id n), refused")
        check_pids(pids, "Stop-Process")
    elif cmd == "kill":
        toks = rest.split()
        pids = []
        skip_next = False
        for t in toks:
            if skip_next:
                skip_next = False
                continue
            tl = t.lower()
            if tl in ("-s", "-n", "--signal"):
                skip_next = True
                continue
            if tl == "-0":
                return  # liveness probe only, not a kill
            if tl in ("-l", "-L"):
                return
            if tl == "-id":
                continue
            if t.startswith("-"):
                continue  # -9 / -TERM / -Force etc.
            if t.startswith("%"):
                continue  # bash job spec
            pids += split_ids(t)
        check_pids(pids, "kill")


def main():
    data = read_payload("guard_kill")
    cmd = ((data.get("tool_input") or {}).get("command") or "") if isinstance(data, dict) else ""
    if not isinstance(cmd, str) or not cmd.strip():
        sys.exit(0)
    for rx, what in NAME_KILL:
        if rx.search(cmd):
            deny(f"Killing processes by name / in bulk is not allowed ({what}). Only taskkill /PID n, Stop-Process -Id n, kill n, and the PID must first be written to kill_allowlist.txt by the main session")
    for stage in SPLIT_STMT.split(cmd):
        check_stage(stage)
    # nested: PID kills inside powershell -Command "..." / bash -c '...'
    if not re.search(r"\b(powershell|pwsh|bash|sh|cmd|zsh)(\.exe)?\b", cmd, I):
        sys.exit(0)
    for inner in re.findall(r"\"([^\"]*)\"|'([^']*)'", cmd):
        for s in inner:
            if s and re.search(r"\b(taskkill|stop-process|spps|kill)\b", s, I):
                for stage in SPLIT_STMT.split(s):
                    check_stage(stage)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
