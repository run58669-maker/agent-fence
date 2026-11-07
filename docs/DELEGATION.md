# Delegation: contract, evidence, kill allowlist

One orchestrating Claude Code session hands work to subagents (and to headless `claude -p` runs started by scheduled tasks). The orchestrator mostly talks, plans and reviews; subagents do the searching, editing and running. That only works if what comes back can be trusted, and if a subagent cannot do damage the orchestrator would not have approved.

## 1. The subagent contract

A `SubagentStart` hook appends this contract to every subagent's context, so it does not depend on the orchestrator remembering to write it into each brief:

1. Kill processes only by a PID that the main session has written to `kill_allowlist.txt`.
2. Credentials never go on a command line, into a screenshot, or into output.
3. The final report ends with `EVIDENCE:` - file paths, commit hashes, URLs, or test output lines.
4. Write one progress line to the output at least every 10 minutes.
5. If something cannot be done, say so; do not make it up.

Rules 1-3 are also enforced by hooks (`guard_kill.py`, `guard_secrets.py`, `guard_subagent_evidence.py`); rules 4-5 are policy only.

## 2. Evidence requirement

`guard_subagent_evidence.py` runs on `SubagentStop`. If the final message claims completion and contains no file path, commit hash, URL or test line, the stop is refused once and the subagent is told to add evidence. The orchestrator then spot-checks the evidence itself (opens the file, runs the test, looks at the output) before reporting the work as done. "The worker said so" is not evidence.

Writing rules for briefs:

- State the goal, what is already ruled out, and the exact scope ("read-only", "do not restart", "do not push").
- "Check" means report only; fixing requires a separate instruction.
- State and progress claims (quota, deploy status, what is live) are checked live, not taken from memory.

## 3. Kill allowlist flow

Name-based kills are blocked outright. A PID kill works only for listed PIDs.

1. List candidates: `Get-CimInstance Win32_Process` with PID, parent PID, start time and command line.
2. Decide what is safe to stop: only processes this system started and no longer needs (orphaned agent process trees from previous days, automation browser instances, finished timers). Long-running daemons (memory MCP servers, watchdogs, the chat front end) and the user's own applications are never on the list.
3. The orchestrator writes the chosen PIDs to `hooks/kill_allowlist.txt`, one per line.
4. Kill by PID (`taskkill /PID n`, `Stop-Process -Id n`, `kill n`).
5. Empty the allowlist afterwards, and report before/after numbers (for example free memory) in one line.

Subagents cannot add PIDs on their own initiative; if a subagent needs a process stopped, it reports the PID and the orchestrator decides.

## 4. Pre-submit review (for anything that leaves the machine)

Adapted from a public write-up of how the Claude Code team does code review:

1. Verify before submitting: run the tests and build, check live behaviour. If a screenshot has to be judged, a fresh-context agent judges it.
2. A fresh-context agent reviews the diff and scores it as a judge would; ideally two in parallel, keeping the intersection to drop false positives.
3. One security pass: credentials only on the server side, input validation, dependencies, logs that leak nothing. Unresolved items block submission.
4. At most three full review rounds; after that only new diffs are reviewed.
5. "Done" comes with evidence: test output, live response, commit hash, screenshot path.
