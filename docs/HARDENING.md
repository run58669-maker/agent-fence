# Hardening the machine's network exposure

Status as of 2026-11-07. Each item is marked **done** or **planned**. Host names, tailnet node names, IP addresses, secret URL paths, tunnel identifiers and process IDs are deliberately left out; services are labelled A-D.

The audit itself was done by subagents under a read-only brief: list processes and listening sockets, read launch scripts and source, query `tailscale serve status` / `funnel status`, send `GET` requests to `127.0.0.1` only. No public addresses were contacted, no `POST`s were sent, nothing was changed.

## 1. Inventory

| Item | Status |
|---|---|
| Listening sockets and their owning processes, launchers (Startup folder, scheduled tasks, watchdogs) and working directories | **done** |
| Public ingress: 1 cloudflared quick tunnel + 8 Tailscale Funnel paths, each traced to a backend, auth checked, last-use evidence collected | **done** |
| Credential inventory: which live services and files reference each bot/webhook token | **done** |

Findings:

- Four local services listen on `0.0.0.0` (a study app, a local API proxy, a chat front end used from a phone, the MCP memory server). Other services already bind `127.0.0.1` only.
- The Windows host firewall is **disabled on all three profiles** (the service itself runs and no group policy forces it off). On a public Wi-Fi profile, anyone on the same network can reach the four services above.
- A **forgotten cloudflared quick tunnel** has been publishing a hackathon prototype for weeks after the event ended. The app has no authentication on any route, its OpenAPI/Swagger UI is exposed, and it runs in "real" mode, so an anonymous `POST` would spend cloud generation credit and write to an object-storage bucket. It is launched from the Startup folder, not from a scheduled task, which is why it was not on anyone's list.
- Of the 8 Funnel paths: 2 have no backend listening at all (any future process on those ports would be published instantly), 1 is a 40-day-unused, unauthenticated endpoint that can spend API credit and write files, 1 belongs to an expired hackathon, 2 are in active use with authentication, and 3 rely only on an unguessable URL path, including one that gives read/write access to the whole memory store.
- A bot token was hardcoded in plaintext in one script. It is already invalid (the API returns 401), but the currently valid token of the same kind is referenced from well over a hundred files, and an old webhook bearer token is still written in a startup script and a notes file even though nothing uses the webhook any more.

## 2. Rebind 0.0.0.0 -> 127.0.0.1

| Step | Status |
|---|---|
| Per-service plan: launcher, exact line to change (CLI flag, env-var default, or constructor argument), restart procedure, verification, rollback | **done** (plan only) |
| Service B (local proxy, no remote users): set the host via an env var in its launcher instead of editing code | planned |
| Service A (study app): change `--host` in its launch script | planned |
| Service D (memory server): change the hard-coded `host=` in the server constructor; restart only when idle | planned |
| Service C (chat front end used from a phone): restart only after two consecutive idle checks 10 s apart, so an in-flight reply is not cut | planned |

Design decisions:

- Bind loopback only and add `tailscale serve --bg --tcp <port> tcp://127.0.0.1:<port>` for the one service the phone needs, instead of binding the tailnet IP as well. Reasons: the watchdogs probe `127.0.0.1` and would restart-loop if loopback disappeared; the tailnet IP changed once already and a hard-coded IP makes the service fail to start (`WinError 10049`) when Tailscale comes up late; serve configuration is per node, not per IP.
- Back up the current serve configuration (`tailscale serve status --json` to a dated file) before touching it, and confirm afterwards that all existing Funnel paths are still present. Run serve commands from PowerShell, not Git Bash (Git Bash rewrites arguments that look like paths).
- Order: firewall first (no restarts needed), verify the phone still connects, then rebind one service at a time with its own backup, restart and check (`Get-NetTCPConnection -LocalPort <port> -State Listen` shows `127.0.0.1`; `GET` on loopback returns the expected status).
- Process stops during the rebind go through the PID allowlist (`guard_kill.py`); the parent watchdog is not killed, it restarts the service with the new configuration.

## 3. Host firewall

| Step | Status |
|---|---|
| Enable all three profiles: `Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True` (elevated) | planned |
| One explicit inbound allow rule for the phone-facing service: TCP on its port, `-InterfaceAlias Tailscale`, `-RemoteAddress 100.64.0.0/10` | planned |
| No allow rules for the proxy or memory server; they are reached only via loopback | planned |
| Verify: phone can connect over the tailnet; Funnel paths still work; another device on Wi-Fi is refused | planned |

Rollback: disable the profiles again and remove the rules by display-name prefix.

## 4. Tunnel and Funnel clean-up

| Step | Status |
|---|---|
| Stop the forgotten quick tunnel and its app (by PID, via the allowlist) and remove its Startup-folder launcher | planned |
| Remove the 2 Funnel paths with no backend | planned |
| Remove the unused camera-review endpoint and the expired-hackathon endpoint | planned |
| For paths that stay and rely only on path secrecy: add bearer-token auth in the server, then treat the old path as compromised (it has appeared in logs and in a private repo's config) | planned |
| Re-run the inventory and diff it against this list | planned |

## 5. Token rotation

| Step | Status |
|---|---|
| Inventory of every file and live service that reads each token (without printing values) | **done** |
| Remove the dead hardcoded token from the script that carried it | planned |
| Rotate the active bot token: create the new one, update the single canonical secrets file, change every reader to load from that file instead of embedding the value, restart the readers by PID, verify with a status-only check, then revoke the old token | planned |
| Void the unused webhook token and delete it from the startup script and notes | planned |
| After rotation, grep the transcript/log directories for the old token's last 4 characters to confirm it was never printed | planned |

The rules applied during rotation are in `SECRETS.md`: the value lives only in a Python variable, logs show status codes or the last 4 characters, no screenshots, and every consumer is updated in the same change so the revoke does not silently break a service.
