"""PreToolUse hook: the main (orchestrating) thread does not search or browse itself; it delegates
to a subagent. Keeps the main context small and makes every lookup go through a subagent whose
report must carry evidence (see guard_subagent_evidence.py).

Main thread vs subagent: for subagent tool calls the hook payload carries agent_id + agent_type;
main-thread calls do not (per the Claude Code hooks docs, "agent_id: Unique identifier for the
subagent..."; confirmed by comparing two raw payloads).
- Has agent_id -> allow, no output.
- Main thread: Grep / Glob / WebFetch / WebSearch -> deny
               Bash / PowerShell command containing grep|egrep|fgrep|rg|find|findstr|Select-String|sls,
                 Get-ChildItem/gci/ls/dir with -Recurse(-r), dir /s -> deny
               Read of a path outside ~/.claude/hooks/ and the memory directory -> deny
  Everything else: no output (normal permission flow).
Payload parse failure -> no output, allow (a broken hook must not wedge the session).

Model gating: only enforced when the main-thread model id contains one of the substrings in
FENCE_MAINLINE_MODELS (comma-separated, default "fable"). The model is taken from the payload's
`model` field, otherwise from the newest non-sidechain assistant message in the last ~200 KB of
transcript_path. Unrecognised -> allow.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hookio import read_payload  # noqa: E402

REASON = "Main thread does not search by itself; delegate to a subagent"
SEARCH_TOOLS = {"Grep", "Glob", "WebFetch", "WebSearch"}
MEMORY_DIR = os.environ.get("FENCE_MEMORY_DIR", os.path.join("~", ".claude", "memory"))
READ_ALLOWED = [
    os.path.normcase(os.path.abspath(os.path.expanduser(os.path.join("~", ".claude", "hooks")))) + os.sep,
    os.path.normcase(os.path.abspath(os.path.expanduser(MEMORY_DIR))) + os.sep,
]
GATED_MODELS = [m.strip().lower() for m in os.environ.get("FENCE_MAINLINE_MODELS", "fable").split(",") if m.strip()]
_W = r"(?<![\w.\-])"   # left side is not a word char / dot / dash
_E = r"(?![\w.\-])"
CMD_PATTERNS = [
    (re.compile(_W + r"(grep|egrep|fgrep|rg|find|findstr)" + _E, re.I), "grep/rg/find/findstr"),
    (re.compile(_W + r"(select-string|sls)" + _E, re.I), "Select-String"),
    (re.compile(_W + r"(get-childitem|gci|ls|dir)" + _E + r"[^|;\n]*\s-r(e(c(u(r(se?)?)?)?)?)?" + _E, re.I), "Get-ChildItem -Recurse"),
    (re.compile(_W + r"dir" + _E + r"[^|;\n]*\s/s" + _E, re.I), "dir /s"),
]


def norm_path(p: str) -> str:
    p = (p or "").strip().strip('"')
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)          # Git Bash form /c/Users/...
    if m:
        p = f"{m.group(1)}:/{m.group(2)}"
    p = os.path.expanduser(p)
    return os.path.normcase(os.path.abspath(p))


def deny(what: str):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"{REASON} (blocked: {what})",
    }}, ensure_ascii=False))


def _model_str(v) -> str:
    if isinstance(v, dict):
        v = v.get("id") or v.get("model") or v.get("display_name") or ""
    return v if isinstance(v, str) else ""


def detect_model(data: dict) -> str:
    """Return the main-thread model id (lower case); "" if it cannot be determined."""
    m = _model_str(data.get("model"))
    if m:
        return m.lower()
    tp = data.get("transcript_path")
    if not tp or not os.path.isfile(tp):
        return ""
    try:
        with open(tp, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 200 * 1024))
            tail = f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line or '"model"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        m = _model_str((e.get("message") or {}).get("model"))
        if m and m != "<synthetic>":
            return m.lower()
    return ""


def main():
    data = read_payload("block_mainline_search")
    if not data or data.get("agent_id"):
        return
    model = detect_model(data)
    if not any(g in model for g in GATED_MODELS):
        return
    tool = data.get("tool_name", "") or ""
    ti = data.get("tool_input", {}) or {}
    if tool in SEARCH_TOOLS:
        return deny(tool)
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command", "") or ""
        for pat, label in CMD_PATTERNS:
            if pat.search(cmd):
                return deny(f"{tool} command contains {label}")
        return
    if tool == "Read":
        p = norm_path(ti.get("file_path", ""))
        if not any(p.startswith(a) for a in READ_ALLOWED):
            return deny(f"Read {ti.get('file_path', '')} (main-thread Read is limited to ~/.claude/hooks/ and the memory dir)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
