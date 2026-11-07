# hooks

Claude Code hooks, Python stdlib only. Each reads the hook JSON payload on stdin. "Block" means exit code 2 with a message on stderr (fed back to the agent), or a PreToolUse `permissionDecision: deny` JSON on stdout. Every hook is **fail-open**: if it cannot parse its input, it allows the call.

| Hook | Event / matcher | Blocks | Allows |
|---|---|---|---|
| `guard_kill.py` | PreToolUse `Bash\|PowerShell` | kill by name (`taskkill /IM`, `/FI`, `pkill`, `killall`, `Stop-Process -Name`, piped `Stop-Process`/`kill`, `xargs kill`, `kill $(pgrep ...)`, `wmic process ... delete`, `Win32_Process Terminate`, `.Kill()`); kill by PID when the PID is not a literal number or not in `kill_allowlist.txt`; also scans commands nested in `powershell -Command "..."` / `bash -c '...'` | everything else; `kill -0` / `kill -l` |
| `guard_secrets.py` | PreToolUse `Bash\|PowerShell\|Read` | credential-looking literals in command text (`AIza...`, `AQ....`, `sk-...`, `ghp_...`, `xox?-`, PEM header); a credential path together with a display command (`cat`, `type`, `Get-Content`, `head`, `echo`, `print(`, `sed -n`, `python -c ...open(` ...); `Read` of a credential path | running a script that reads the file internally (`py -3 x.py`) |
| `guard_memory.py` | PreToolUse `Bash\|PowerShell` | delete/move verbs against the protected memory store, `.claude/projects/*/memory`, `.claude/CLAUDE.md`, private uploads; removing hooks from `settings.json`; disabling memory-maintenance scheduled tasks | backups / temp files (`.bak`, `.tmp`, `backups/`, `-wal`, `-shm`, `__pycache__`); any command while a cooling-off flag aged 12-48 h exists |
| `guard_subagent_evidence.py` | SubagentStop | a final message that claims completion (`done` / 完成 / 做完 / 已上线 / 已推) without any evidence marker (file path, commit hash, URL, line starting with `Tests`/测试) | messages without a claim; `stop_hook_active=true` (bounces at most once) |
| `block_mainline_search.py` | PreToolUse `Grep\|Glob\|WebFetch\|WebSearch\|Bash\|PowerShell\|Read` | main-thread search/browse tools, recursive listing / grep in shell commands, `Read` outside `~/.claude/hooks/` and the memory dir. Only when the main-thread model id contains a substring from `FENCE_MAINLINE_MODELS` (default `fable`) | all subagent calls (payload has `agent_id`); other models |
| `block_mainloop_execution.py` | PreToolUse `Edit\|Write\|NotebookEdit\|Bash` | nothing (it used to force delegation with `ask`; relaxed) | auto-`allow` for read-only main-loop Bash (`git status/log/diff/show`, `ls`, `cat`, render/notify scripts) |
| `_hookio.py` | helper | | UTF-8 stdin parsing with cp936 fallback, UTF-8/LF stdout |
| `_mode.py` | helper | | reads `hooks/mode` (`default` / `work`); used by context-injection hooks not included here |

## kill_allowlist.txt

Plain text next to `guard_kill.py`, one PID per line. The flow is in `../docs/DELEGATION.md`: the orchestrating session inspects the process (`Get-CimInstance Win32_Process` for PID, start time, command line), writes the PID, the kill happens by PID, the file is emptied afterwards. A missing file means no PID may be killed.

## memory_delete_ok.flag

An empty file next to `guard_memory.py`. It only unlocks deletion when its modification time is between 12 and 48 hours old, so it has to be created the day before and cannot be created and used immediately after creation.

## Configuration

- `guard_memory.py`: edit `PROTECTED` and `TASK_NAMES`; the shipped names (`memstore`, `agent_archive`, `private_photos`) are placeholders.
- `block_mainline_search.py`: `FENCE_MEMORY_DIR` (default `~/.claude/memory`), `FENCE_MAINLINE_MODELS` (default `fable`).
- `_hookio.py` logs decode problems to `~/.claude/logs/hookio.log`.

## Tests

`py -3 hooks/tests/smoke_test.py` feeds 19 sample payloads and checks exit codes / decisions. It does not cover every regex branch.

## Rollback

Per hook: delete its entry from `hooks` in `settings.json` (keep a dated backup of `settings.json` before editing). The hooks write nothing except `~/.claude/logs/hookio.log`, so removing the entry fully disables them. To loosen temporarily without editing settings: `guard_kill` - add the PID to `kill_allowlist.txt`; `guard_memory` - the cooling-off flag; `block_mainline_search` - set `FENCE_MAINLINE_MODELS` to a value that matches no model.
