#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PreToolUse hook: main loop (non-subagent) Edit/Write/NotebookEdit/Bash.
- Subagent call (payload has agent_id) -> allow, no output.
- Main-loop call (no agent_id):
    - Bash and the command matches the read-only / finishing allowlist -> allow
    - anything else -> no output, normal permission flow.
History: this hook used to answer "ask" for everything outside the allowlist, forcing delegation
to a subagent. It was relaxed so the main loop decides itself whether to do or delegate; the
auto-allow for read-only commands remains.
"""
import json
import re
import sys, os as _os_
sys.path.insert(0, _os_.path.dirname(_os_.path.abspath(__file__)))

# Read-only / light finishing commands (Bash only)
WHITELIST_PATTERNS = [
    r"^\s*git\s+(status|log|diff|show)\b",
    r"^\s*ls\b",
    r"^\s*cat\b",
    r"^\s*(python|py)\s+.*render.*\.py",
    r"^\s*(python|py)\s+.*notify.*\.py",
]


def is_whitelisted_bash(command: str) -> bool:
    for pat in WHITELIST_PATTERNS:
        if re.search(pat, command, re.IGNORECASE):
            return True
    return False


def main():
    try:
        from _hookio import read_payload as _rp; raw = __import__("json").dumps(_rp("block_mainloop_execution"), ensure_ascii=False)
        data = json.loads(raw) if raw else {}
    except Exception:
        # input parse failure: do not block
        return

    # subagent call -> allow, no output
    if data.get("agent_id"):
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}

    if tool_name == "Bash":
        command = tool_input.get("command", "") or ""
        if is_whitelisted_bash(command):
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "Main-loop Bash allowlisted command (read-only / board render), auto-allowed."
                }
            }))
            return

    # Silent pass -> normal permission flow.
    return


if __name__ == "__main__":
    main()
