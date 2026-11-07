# agent-fence

A set of defensive fences I run around Claude Code multi-agent work on my own Windows machine, as a single developer. It is not a product; it is what I actually use day to day, published with personal details and credentials removed.

## What this is

I run one orchestrating Claude Code session plus many subagents and scheduled headless `claude -p` runs on one personal Windows 11 machine, alongside a handful of local services (an MCP memory server, a chat front end, hackathon prototypes). Over a few months the agents made a series of concrete mistakes: killing processes by name and taking down the wrong service, printing an API key into a log and later capturing a rotated key in a screenshot, reporting work as "done" with nothing to back it up, deleting their own long-term memory on an in-the-moment instruction, and stating numbers and past events that never happened.

Each fence here was added after one of those incidents. They are Claude Code hooks (PreToolUse / Stop / SubagentStop) plus written operating rules for delegation and credentials, and a hardening inventory of what the machine exposes to the network.

## Threat model

What I am defending against is mostly **my own agents making a confident mistake**, not a malicious adversary:

| Risk | Example that actually happened | Fence |
|---|---|---|
| Collateral process kills | Name-based kill took down an unrelated dev server on the same port | `hooks/guard_kill.py` + PID allowlist |
| Credential leakage into transcripts | Key printed to a terminal log; next key captured in a screenshot; both had to be revoked | `hooks/guard_secrets.py`, `docs/SECRETS.md` |
| Unverified completion claims | Subagent says "done" with no path, commit, URL or test output | `hooks/guard_subagent_evidence.py` |
| Irreversible destruction of agent memory | Memory store, CLAUDE.md, startup hooks and maintenance tasks all sealed in one session | `hooks/guard_memory.py` |
| Hallucinated facts in replies | Invented a hackathon final and prize; "never earned anything" when a payout existed | `factgate/fact_gate.py` |
| Main-thread context sprawl | Orchestrator greps and browses itself instead of delegating | `hooks/block_mainline_search.py` |
| Network exposure of local services | Services bound to 0.0.0.0 with the host firewall off; a forgotten quick tunnel to an unauthenticated app | `docs/HARDENING.md` (audit done, fixes planned) |

Out of scope: a determined attacker with code execution on the machine, prompt-injection-driven exfiltration through channels the hooks do not see, and anything that runs outside Claude Code's hook system.

## Components

```
hooks/              PreToolUse / SubagentStop hooks (Python, stdlib only)
  guard_kill.py               no kill-by-name; kill-by-PID only for allowlisted PIDs
  guard_secrets.py            no credential literals on command lines; no displaying credential files
  guard_memory.py             no deleting/moving the protected memory store without a cooling-off flag
  guard_subagent_evidence.py  subagent "done" reports must carry evidence
  block_mainline_search.py    main thread delegates search/browse to subagents (model-gated)
  block_mainloop_execution.py auto-allows read-only main-loop Bash commands
  _hookio.py, _mode.py        shared helpers
  tests/smoke_test.py         payload-level smoke tests
factgate/           Stop hook: fact-check gate on the last reply (Haiku via `claude -p`)
docs/
  HARDENING.md          network exposure inventory and rebind/firewall/tunnel/token plan
  SECRETS.md            credential handling rules for agents
  DELEGATION.md         subagent contract, evidence rule, kill-allowlist flow, pre-submit review
  CONTAINMENT_NOTES.md  mapping to Anthropic's agent containment best practices, and the gaps
settings.example.json   hook wiring (event -> matcher -> command)
```

See `hooks/README.md` and `factgate/README.md` for per-component behaviour and rollback.

## How to install

Requirements: Windows, Python 3.10+ on PATH as `py`, Claude Code with hooks support.

1. Back up your settings: `copy %USERPROFILE%\.claude\settings.json %USERPROFILE%\.claude\settings.json.bak-YYYYMMDD`.
2. Copy `hooks/` and `factgate/` to `%USERPROFILE%\.claude\agent-fence\` (or anywhere; the paths in step 3 must match).
3. Merge the `hooks` block from `settings.example.json` into your `settings.json`, replacing `<HOME>` with your home directory. Add only the hooks you want.
4. Edit the placeholders in `hooks/guard_memory.py` (`PROTECTED`, `TASK_NAMES`) to point at your own memory store.
5. Run `py -3 hooks/tests/smoke_test.py`; it should print `ALL PASS`.
6. The log file is created at runtime; it is not included in the repository. For `factgate`, start in `--mode log` (only logs verdicts, never blocks) and read `factgate/logs/factgate.jsonl` for a day before switching to `--mode block`.

Rollback: remove the corresponding entry from `settings.json`, or restore the backup from step 1. None of the hooks modify anything outside their own log files.

## Limitations

- **Not a sandbox.** These are process-level guardrails on tool calls. Everything runs as my user, with my files and credentials reachable. Anthropic's guidance for autonomous agents is a hardware-virtualized sandbox per agent; I do not have that here (see `docs/CONTAINMENT_NOTES.md`).
- **Bypassable.** Hooks pattern-match command text. Obfuscated commands, a script that does the forbidden thing internally, or a tool the matcher does not cover will get through. Running Claude Code with bypass-permissions mode does not disable hooks, but it removes the permission prompts that are the second line of defence, and an agent that can edit `settings.json` can remove the hooks (`guard_memory.py` catches only the obvious form of that).
- **Fail-open.** Every hook allows the call when its own input parsing fails, so a broken hook never wedges a session. That is a deliberate availability-over-safety trade-off.
- **Windows-specific.** Paths, `taskkill`/`Stop-Process`/`wmic` handling and the cp936 stdin fallback assume Windows. Some POSIX forms (`kill`, `pkill`) are covered because Git Bash is used too.
- **Regex false positives and negatives.** `guard_secrets.py` blocks any command that both mentions a credential-like path and a display verb, including harmless ones; it misses credentials it has no pattern for.
- **factgate is probabilistic.** It uses a small model and will miss things and occasionally flag supported claims; its prefilter is tuned for Chinese-language replies.
- **Hardening is partly planned, not done.** `docs/HARDENING.md` marks each item `done` or `planned`; most fixes there are planned.

## License

MIT, see `LICENSE`.
