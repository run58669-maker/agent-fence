"""SubagentStop hook: a subagent that claims "done" must attach evidence.

Payload fields (checked against the built-in schema of the Claude Code build in use):
hook_event_name=SubagentStop, stop_hook_active, agent_id, agent_type,
agent_transcript_path, last_assistant_message.

- last_assistant_message contains a completion claim (完成 / done / 做完 / 已上线 / 已推)
  and no evidence marker -> exit 2 + stderr, the subagent is sent back to add evidence.
- Evidence markers: Windows/Unix file path, commit hash [0-9a-f]{7,}, http(s) URL,
  a line starting with "Tests"/"测试".
- No message / stop_hook_active=true (already bounced once, prevents loops) / any exception -> allow (exit 0).
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Claim words are bilingual on purpose: the agents report in Chinese and English.
CLAIM = re.compile(r"完成|做完|已上线|已推|(?<![A-Za-z])done(?![A-Za-z])", re.I)
EVIDENCE = [
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\/][^\s`'\"<>|]+"),           # Windows path
    re.compile(r"(?<![\w.:/])(?:~|\.{1,2})?/[\w.\-]+/[\w.\-/]+"),       # Unix path (at least two segments)
    re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![0-9A-Za-z])"),  # commit hash (must mix digits and letters)
    re.compile(r"https?://\S+", re.I),                                  # URL
    re.compile(r"^\s*(?:[-*>|]\s*)?(?:Tests?(?![A-Za-z])|测试)", re.I | re.M),  # test line
]
REASON = "Report lacks evidence: attach a file path / commit / URL / test line and resubmit"


def has_evidence(msg: str) -> bool:
    return any(rx.search(msg) for rx in EVIDENCE)


def main():
    from _hookio import read_payload
    p = read_payload("guard_subagent_evidence")
    if p.get("stop_hook_active"):
        return 0
    msg = p.get("last_assistant_message")
    if not isinstance(msg, str) or not msg.strip():
        return 0
    if CLAIM.search(msg) and not has_evidence(msg):
        try:
            sys.stderr.buffer.write((REASON + "\n").encode("utf-8"))
            sys.stderr.flush()
        except Exception:
            pass
        return 2
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        rc = 0
    sys.exit(rc)
