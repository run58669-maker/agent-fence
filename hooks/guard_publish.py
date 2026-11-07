"""PreToolUse hook: subagents may not publish anything. Publishing is a main-thread action,
taken only after a human has looked at the target account / repository.

Detection: the PreToolUse payload carries `agent_id` when the call comes from a subagent;
no `agent_id` means the main thread, which is always allowed through.

Blocked for subagents (Bash / PowerShell command text):
  - git push (including -f / --force / --mirror)
  - gh repo create / gh release create / gh pr create / gh pr merge
  - git remote add / set-url (prevents attaching a remote first and pushing later)
  - npm publish / pip upload / twine upload / cargo publish
  - vercel --prod / netlify deploy --prod / wrangler deploy / fly deploy / railway up
    / gcloud app deploy
Block = PreToolUse `permissionDecision: deny` with a reason; the subagent is expected to report
what should be pushed to the main thread.

Fail-open: unparseable input, no `agent_id`, a tool other than Bash/PowerShell, or any
exception -> no output, exit 0 (allow).

Motivating incident: a subagent told to assemble a repository locally without pushing instead
created the public repository and pushed on its own; the push gate did not exist yet.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hookio import read_payload  # noqa: E402

REASON = ("Subagents may not publish (git push / gh repo create / deploy): report what should be "
          "pushed to the main thread, which pushes after a human review of the target")
_W = r"(?<![\w.\-])"
_E = r"(?![\w.\-])"
PATTERNS = [
    (re.compile(_W + r"git" + r"(?:\s+-[\w=-]+)*\s+push" + _E, re.I), "git push"),
    (re.compile(_W + r"git" + r"(?:\s+-[\w=-]+)*\s+remote\s+(add|set-url)" + _E, re.I), "git remote add/set-url"),
    (re.compile(_W + r"gh\s+(repo\s+create|release\s+create|pr\s+(create|merge))" + _E, re.I), "gh create/merge"),
    (re.compile(_W + r"npm\s+publish" + _E, re.I), "npm publish"),
    (re.compile(_W + r"(twine\s+upload|pip\s+upload|cargo\s+publish)" + _E, re.I), "package upload"),
    (re.compile(_W + r"vercel" + _E + r"[^|;\n]*--prod" + _E, re.I), "vercel --prod"),
    (re.compile(_W + r"(wrangler|fly|railway)\s+(deploy|up)" + _E, re.I), "deploy"),
    (re.compile(_W + r"netlify\s+deploy" + _E + r"[^|;\n]*--prod" + _E, re.I), "netlify --prod"),
    (re.compile(_W + r"gcloud\s+app\s+deploy" + _E, re.I), "gcloud deploy"),
]


def deny(what: str):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"{REASON} (blocked: {what})",
    }}, ensure_ascii=False))


def check(cmd: str):
    for rx, what in PATTERNS:
        if rx.search(cmd):
            return what
    return None


def main():
    data = read_payload("guard_publish")
    if not data or not data.get("agent_id"):
        return 0
    if data.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    what = check(cmd)
    if what:
        deny(what)
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        rc = 0
    sys.exit(rc)
