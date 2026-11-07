r"""PreToolUse hook: protect the agent's long-term memory store from deletion or relocation.

Purpose: protect the memory store, CLAUDE.md, startup context-injection hooks and
scheduled maintenance tasks against accidental deletion or relocation. This hook makes
that class of irreversible action require a cooling-off period, for every agent on the machine
(main thread, subagents, headless `claude -p` runs started by scheduled tasks).

Blocked (a Bash / PowerShell command segment contains both a dangerous verb and a protected target):
- delete/move verbs: rm rmdir rd del erase unlink mv move ren Remove-Item ri Move-Item mi Rename-Item
                     shutil.rmtree shutil.move os.remove os.unlink os.rename os.replace Path.unlink
- protected targets: the protected memory store directory and its databases, the agent's private
                     archive directory, .claude/projects/*/memory, .claude/CLAUDE.md, the private
                     photo directory and .claude/uploads (original uploaded files)
- stripping hooks: a command that mentions settings.json together with pop/del/clear/remove on hooks
- stopping tasks: Disable-ScheduledTask / schtasks /change /disable / Unregister-ScheduledTask
                  that mention the memory-maintenance task names
Allowed:
- targets that are obviously backups or temp files (.bak / .tmp / backups/ / -wal / -shm / __pycache__)
- cooling-off pass: hooks/memory_delete_ok.flag exists, created more than 12 hours ago and less
  than 48 hours ago (a newly created flag does not count yet)
Block = exit 2 + stderr.

Configure PROTECTED and TASK_NAMES for your own layout; the names below are neutral placeholders.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG = os.path.join(HERE, "memory_delete_ok.flag")
I = re.I

DANGER = re.compile(
    r"(?<![\w-])(rm|rmdir|rd|del|erase|unlink|mv|move|ren|remove-item|ri|move-item|mi|rename-item)(?![\w-])"
    r"|shutil\.(rmtree|move)|os\.(remove|unlink|rename|replace|rmdir)|\.unlink\(",
    I,
)
# memstore = protected memory store directory; memstore.db / archive.db = its databases;
# agent_archive = the agent's private archive; private_photos / .claude/uploads = user-provided originals.
PROTECTED = re.compile(
    r"desktop[\\/]+memstore(?![\w-])|(?<![\w.\\/-])memstore(?=[\/\"' ]|$)|memstore\.db|archive\.db|agent_archive|[\\/]memory(?![\w.-])|[\\/]memory[\\/]"
    r"|\.claude[\\/]+claude\.md"
    r"|private_photos|\.claude[\\/]+uploads",
    I,
)
SAFE_TARGET = re.compile(r"\.bak|\.tmp\b|[\\/]backups[\\/]|-wal\b|-shm\b|__pycache__", I)
HOOK_STRIP = re.compile(r"settings(\.local)?\.json", I)
HOOK_VERB = re.compile(r"(\.pop\(|\bdel\b|\.clear\(|remove)[^\n]{0,80}hooks|hooks[^\n]{0,80}(\.pop\(|\bdel\b|\.clear\(|=\s*\{\s*\}|=\s*\[\s*\])", I)
TASK_OFF = re.compile(r"disable-scheduledtask|unregister-scheduledtask|schtasks[^\n]*?/(change[^\n]*?/disable|delete)", I)
TASK_NAMES = re.compile(r"memstore|consolidat|memory|brainloop", I)


def flag_ok():
    try:
        age = time.time() - os.path.getmtime(FLAG)
        return 12 * 3600 <= age <= 48 * 3600
    except Exception:
        return False


def deny(why):
    msg = (
        "[guard_memory] blocked: " + why + "\n"
        "The protected memory store is not deleted or moved on an in-the-moment instruction.\n"
        "Do not work around this. If the deletion is still wanted after a cooling-off period,\n"
        "create hooks/memory_delete_ok.flag; it becomes valid 12 hours later and expires at 48 hours."
    )
    try:
        sys.stderr.buffer.write((msg + "\n").encode("utf-8"))
        sys.stderr.flush()
    except Exception:
        pass
    sys.exit(2)


def main():
    try:
        p = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return
    if p.get("tool_name") not in ("Bash", "PowerShell"):
        return
    cmd = str((p.get("tool_input") or {}).get("command") or "")
    if not cmd or flag_ok():
        return
    # Look at one statement at a time, so "cp to backup on this line, rm something else on that line"
    # is not joined into a false match.
    for seg in re.split(r"[\n;]|&&|\|\|", cmd):
        if DANGER.search(seg) and PROTECTED.search(seg):
            rest = PROTECTED.sub("", seg)  # unused (pre-existing dead code, kept as-is)
            if SAFE_TARGET.search(seg) and not re.search(r"(memstore|memory|agent_archive|private_photos|uploads)[\/\"' ]*$", seg.strip(), I):
                continue
            deny("deleting or moving the protected memory store / agent archive / CLAUDE.md / private uploads")
        if TASK_OFF.search(seg) and TASK_NAMES.search(seg):
            deny("disabling a scheduled task that maintains the memory store")
    if HOOK_STRIP.search(cmd) and HOOK_VERB.search(cmd):
        deny("removing context-injection / memory hooks from settings.json")


if __name__ == "__main__":
    main()
