# Notes against Anthropic's agent containment best practices

Source: Anthropic, "Agent Containment Best Practices: Getting Started" (https://support.claude.com/en/articles/17316076), read 2026-11-07. Quotes below are from that page.

Summary: the recommended baseline is a hardware-virtualized sandbox per agent with credentials outside it and egress denied by default. I do not have that. What this repository provides is a **process-level fence inside a normal user account**: hooks that inspect tool calls, written rules, and an allowlist for the most destructive operation (killing processes). It reduces the blast radius of agent mistakes; it does not contain a hostile agent.

| Recommendation | What I do | Gap |
|---|---|---|
| "Run every autonomous agent inside a hardware-virtualized sandbox" (reference: one microVM per agent, Kata Containers with Firecracker, internal network) | Agents run directly on the host under my user account. | **Large.** No VM, no container, no filesystem isolation. Everything my user can read, an agent can read. |
| Without a sandbox, "review every write and don't run anything the agent wrote without reading it" | Edits by the orchestrator are reviewed in the session; subagent work is spot-checked before it is reported as done (`DELEGATION.md`). Pushes and anything public are done by hand after review. | Not every write is read line by line; scheduled headless runs write without a live reviewer. |
| "Never mount credential-bearing paths into the agent's environment"; keep the model-API credential in a proxy outside | `guard_secrets.py` blocks credential literals on command lines, display of credential files, and `Read` of them. Model-API calls from hooks go through the subscription CLI; the paid-API key is only read from the environment and is off by default. | Credential files are on the same disk and reachable by any script an agent writes. No credential-injecting proxy. |
| Deny egress by default; "Allowlist only the in-scope targets" | None for agents. For inbound exposure, an audit and a plan to bind services to loopback, enable the host firewall and remove stale tunnels (`HARDENING.md`). | **Large.** Agents have unrestricted outbound network access. |
| "Run Claude Code agents in auto permission mode as an extra check" and describe the environment to the classifier | Hooks act as the extra check on top of whatever permission mode is in use. | I do not consistently run in auto mode; some sessions run with bypass permissions, where hooks are the only check. |
| "Keep agent transcripts and proxy logs for at least 30 days, review them during and after runs" | Claude Code transcripts are kept on disk; factgate writes a JSONL log of every verdict; a hook logs decode errors. | No scheduled scan of transcripts; review happens when something looks wrong. |
| "Review the configuration and run a supervised escape test on each new host, after each sandbox change, and with each new model" | Payload-level smoke tests for each hook (`hooks/tests/smoke_test.py`), factgate test cases. | No adversarial test of the hooks against a model actively trying to bypass them. |
| "State the scope in the instructions you give each agent" | Every brief states scope (read-only / no restarts / no push); a `SubagentStart` hook injects a fixed contract into every subagent. | Scope is stated in text; nothing enforces "read-only" except the specific hooks. |
| "Put an observable proxy or tool between the agent and the target" | Process kills go through a PID allowlist the orchestrator controls. Destructive operations on the memory store need a cooling-off flag. | Only these two operations are brokered; file writes, network calls and other commands go direct. |
| "Watch runs that have network access, limit every agent's turns and run time, and know how to stop an agent" | Subagents must report progress every 10 minutes; one-turn work is kept under about 10 minutes, longer work moves to the background with a report first. | Limits are policy, not enforced; no hard per-agent timeout beyond the hook timeouts. |
| "Do not point autonomous agents at live systems whose failure could endanger safety or critical services" | Agents work on my own machine, personal projects and hackathon prototypes. | Not applicable in the safety-critical sense; my own machine is the live system. |

## What the fences are honest about

- Hooks match command text. A script that performs a blocked action internally is not seen.
- Every hook fails open on its own errors.
- An agent with write access to `~/.claude/settings.json` can remove the hooks; `guard_memory.py` only catches the obvious forms.
- The fences are Windows-specific.

## What would close the biggest gaps

1. Run autonomous and scheduled agents in a VM (or at least a separate low-privilege Windows account) with no access to the credential directory.
2. Egress allowlist for that VM or account.
3. A credential-injecting proxy so the model-API key never enters the agent environment.
4. A scheduled transcript scan for credential patterns and for writes outside the task's stated scope.
