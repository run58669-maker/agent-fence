# factgate

A Claude Code **Stop** hook that fact-checks the assistant's final reply of each turn. If the reply states numbers, dates, past events, current status, quotes of what the user said, or facts about external entities, and nothing in the recent evidence supports them, and they are not marked as an unverified impression, the turn is bounced once so the agent checks with tools or rewrites the sentence as "unverified".

Why: in two days the agent produced seven unsupported statements, among them a hackathon final that never took place, a wrong deadline, two credits mixed up, "never earned anything" while a payout existed, and a wrong claim about a company's funding. Writing the lesson into memory did not help; a mechanism was needed.

## How it works

1. Claude Code fires `Stop` at the end of each turn; stdin carries `transcript_path`, `stop_hook_active`, `last_assistant_message` (checked against code.claude.com/docs/en/hooks).
2. `stop_hook_active=true` -> allow immediately (block at most once, never loop).
3. Read the last 8 MB of the transcript. Evidence = the user's last 6 messages, plus everything since then: the agent's tool calls, tool results, subagent notifications, and hook-injected context. Memory blocks injected at session start count only as "the memory store records this", not as proof that something happened.
4. Cheap regex prefilter (digits, time words, "remember / said / already / never", quotations, funding / deadline / prize / quota ...). No hit -> allow without calling a model (about 0.2 s). Casual conversation mostly stops here.
5. On a hit, ask Haiku through `claude -p --model claude-haiku-5-5` (subscription route), from an empty working directory, with CLAUDE.md and auto-memory disabled and `--tools ""`. It lists at most 4 unsupported, unmarked claims; the instruction is "when in doubt, don't report", except for the hard rule below.
6. Hard rule, **assigned is not done**: claims about what the user did or said are only supported by the user's own words or images. Plans, push notifications, assignments and memory notes saying "pending / sent" do not count.
7. Found -> print `{"decision":"block","reason":"..."}` with exit 0 (only in `block` mode). Nothing found / error / timeout -> allow silently.
8. Log: `factgate/logs/factgate.jsonl` (verdict, latency, flagged claims; no credentials).

## Modes and settings

| Variable / flag | Default | Meaning |
|---|---|---|
| `--mode` / `FACTGATE_MODE` | `log` | `log`: full check, write the log, always allow. `block`: bounce on findings. |
| `FACTGATE_BUDGET` | `9` | total seconds per verdict; over budget -> allow |
| `FACTGATE_ROUTES` | `cli` | `cli` = `claude -p` on the subscription; `api` = paid API with `FACTGATE_API_KEY` from the environment (off by default) |
| `FACTGATE_CLAUDE` | `claude` on PATH | path to the Claude Code CLI |
| `FACTGATE_CHILD` | unset | set to `1` in the child process so a nested Stop hook passes through |

Set the hook `timeout` in settings to about 10 s.

## Cost and latency (measured locally)

- Prefilter pass: about 0.2 s, zero tokens.
- Model call: about 3-6 s per call, roughly 1.5-4k input tokens, on the subscription quota.
- Expected: about 100-200 turns a day, 30-60 of them reach the model.

## Known limitations

- Haiku misses things and sometimes flags supported claims; the false-positive rate on real long conversations is not measured yet. That is why the default is `log`.
- Only the final reply text is checked; text earlier in the same turn is not.
- The prefilter is tuned for Chinese-language replies. English replies without digits will mostly pass the prefilter unchecked.
- Adds 3-6 s to turns that hit the prefilter.

## Install

1. Back up `settings.json`.
2. Add to `hooks.Stop` (see `../settings.example.json`):
```json
{ "matcher": "", "hooks": [ { "type": "command", "command": "py \"<HOME>/.claude/agent-fence/factgate/fact_gate.py\" --mode log", "timeout": 10 } ] }
```
3. Watch `logs/factgate.jsonl` for a day, then switch to `--mode block`.

## Rollback

Remove that entry (or restore the backup). The script writes nothing outside `factgate/logs/`.

## Tests

From the repository root, `py -3 factgate/tests/make_and_run.py [--mode log|block] [t1 t2 ...]` writes fake transcripts and runs the gate on them. t4 and t5 never call the model; the others do.

| Case | Shape | Expected |
|---|---|---|
| t1_fake_final | reply describes a hackathon final and prize; tool result says there is no final and nothing was submitted | block |
| t2_never_earned | "I have never earned anything", no evidence | block |
| t3_deepseek_marked | funding claim prefixed "this is my impression, unverified" | pass |
| t4_casual | small talk, no factual markers | pass (prefilter) |
| t5_active_no_loop | same as t1 with `stop_hook_active=true` | pass |
| t6_supported | numbers taken from this turn's tool result | pass |
| t7_assigned_not_done | only a push-notification log; reply says the user finished the work | block |
