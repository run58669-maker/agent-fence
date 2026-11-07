"""Smoke tests: feed sample payloads to each hook and check exit code / decision. Run: python hooks/tests/smoke_test.py"""
import json, subprocess, sys, os
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = [
    ("guard_kill.py", {"tool_name": "Bash", "tool_input": {"command": "taskkill /IM chrome.exe /F"}}, 2),
    ("guard_kill.py", {"tool_name": "Bash", "tool_input": {"command": "taskkill /PID 999999 /F"}}, 2),
    ("guard_kill.py", {"tool_name": "Bash", "tool_input": {"command": "pkill -f node"}}, 2),
    ("guard_kill.py", {"tool_name": "Bash", "tool_input": {"command": "git status"}}, 0),
    ("guard_secrets.py", {"tool_name": "Bash", "tool_input": {"command": "cat ~/secrets/gemini.json"}}, 2),
    ("guard_secrets.py", {"tool_name": "Bash", "tool_input": {"command": "curl -H 'x: sk-" + "a" * 24 + "'"}}, 2),
    ("guard_secrets.py", {"tool_name": "Read", "tool_input": {"file_path": "C:/x/.env"}}, 2),
    ("guard_secrets.py", {"tool_name": "Bash", "tool_input": {"command": "py -3 deploy.py"}}, 0),
    ("guard_memory.py", {"tool_name": "Bash", "tool_input": {"command": "rm -rf ~/.claude/projects/p/memory"}}, 2),
    ("guard_memory.py", {"tool_name": "PowerShell", "tool_input": {"command": "Remove-Item C:/data/memstore.db"}}, 2),
    ("guard_memory.py", {"tool_name": "Bash", "tool_input": {"command": "rm C:/data/memstore.db.bak-20261107"}}, 0),
    ("guard_memory.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}}, 0),
    ("guard_publish.py", {"agent_id": "a1", "tool_name": "Bash", "tool_input": {"command": "git push -f origin main"}}, "deny"),
    ("guard_publish.py", {"agent_id": "a1", "tool_name": "Bash", "tool_input": {"command": "gh repo create x --public"}}, "deny"),
    ("guard_publish.py", {"agent_id": "a1", "tool_name": "Bash", "tool_input": {"command": "git status"}}, 0),
    ("guard_publish.py", {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}, 0),
    ("guard_subagent_evidence.py", {"hook_event_name": "SubagentStop", "last_assistant_message": "done, all good"}, 2),
    ("guard_subagent_evidence.py", {"hook_event_name": "SubagentStop", "last_assistant_message": "done: C:/repo/out.txt"}, 0),
    ("guard_subagent_evidence.py", {"hook_event_name": "SubagentStop", "stop_hook_active": True, "last_assistant_message": "done"}, 0),
    ("block_mainline_search.py", {"tool_name": "Grep", "model": "claude-fable-5", "tool_input": {}}, "deny"),
    ("block_mainline_search.py", {"tool_name": "Grep", "model": "claude-opus-5-5", "tool_input": {}}, 0),
    ("block_mainline_search.py", {"tool_name": "Grep", "agent_id": "a1", "model": "claude-fable-5", "tool_input": {}}, 0),
    ("block_mainloop_execution.py", {"tool_name": "Bash", "tool_input": {"command": "git status"}}, "allow"),
]
bad = 0
for hook, payload, want in CASES:
    r = subprocess.run([sys.executable, os.path.join(H, hook)], input=json.dumps(payload).encode(), capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    if want in ("deny", "allow"):
        got = want if f'"permissionDecision": "{want}"' in out else f"rc={r.returncode} out={out[:60]!r}"
        ok = got == want
    else:
        got = r.returncode
        ok = got == want
    bad += not ok
    print("OK " if ok else "XX ", hook, json.dumps(payload.get("tool_input") or payload.get("last_assistant_message"))[:70], "->", got)
print("ALL PASS" if not bad else f"{bad} FAILED")
