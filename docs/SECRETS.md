# Credential handling for agents

These rules go into every task brief that touches a credential. They exist because of one afternoon: an agent configuring a hosting service printed an API key into the terminal log, and the agent sent to rotate it captured the new key in a screenshot. Both keys had to be revoked; the third one stayed clean. Several other services had the old key hard-coded and broke on revoke.

**Why it matters:** agent stdout and screenshots are stored in the session transcript, which is effectively plaintext on disk. A credential that appears once has to be rotated, and every rotation means updating every consumer.

## Rules

1. **Never print.** The value only exists in a Python variable. stdout and logs report a status code or the last 4 characters at most.
2. **Never screenshot.** When a credential has to be read from a web page, read it from the DOM into a variable; do not look at it through a screenshot.
3. **Web forms:** fill credential fields with CDP `Input.insertText` after clearing the field first (some dashboards pre-fill the old value).
4. **Before rotating,** find every live consumer of the credential (local services, `.env` files, hosting-provider environment variables) and update them in the same change. Restart long-running services carefully (wait until they are idle).
5. **Stopping local services:** only the PIDs you started yourself, through the kill allowlist. Never match by process name or file name (the same afternoon, a name match killed an unrelated dev server).

## Enforcement

`hooks/guard_secrets.py` enforces rules 1 and part of 2 mechanically:

- command text containing a credential-shaped literal is blocked;
- a command that both names a credential path (`secrets/`, `.env`, `*_key*.md`, token-named files) and uses a display verb is blocked;
- `Read` of a credential path is blocked;
- running a script that reads the file internally is allowed.

The subagent contract (`DELEGATION.md`) repeats the rule in every subagent's context at start-up.

## Known gaps

- A script can still print the value; the hook only sees the command line, not what the script does.
- Credential formats without a pattern in `KEY_LITERALS` are not recognised.
- Screenshots are a policy rule only; there is no hook on image capture.
