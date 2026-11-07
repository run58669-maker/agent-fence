"""PreToolUse hook: credentials never go on a command line and are never printed.
Applies to the main thread and every subagent.

Bash / PowerShell:
  1) The command text contains something that looks like a credential literal
     (AIza... / AQ.... / sk-... / ghp_... / xox?- / PEM header) -> block.
  2) The command contains both a "credential path" and a "display" command
     (cat/type/Get-Content/head/tail/more/less/echo/Write-Host/Write-Output/print(/sed -n/
     python -c open(...)) -> block.
     Merely running a script (py -3 x.py / python x.py) is not display and is allowed:
     the script reads the file inside Python and keeps the value in a variable.
Read: file_path is a credential path -> block.

Credential path = contains \\secrets\\ or /secrets/; or file name .env / .env.*, gemini.json, *_key*.md;
                  or a non-source file under Desktop whose name contains "token".
Block = exit 2 + stderr (UTF-8). Empty / unknown / parse failure -> exit 0 (allow).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _hookio import read_payload  # noqa: E402
except Exception:  # pragma: no cover
    def read_payload(caller="?"):
        import json
        try:
            return json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return {}

I = re.I
REASON = "Credentials must not appear on the command line or be printed"

KEY_LITERALS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"AQ\.[0-9A-Za-z_\-]{20,}"),
    re.compile(r"sk-[0-9A-Za-z]{20,}"),
    re.compile(r"ghp_[0-9A-Za-z]{30,}"),
    re.compile(r"xox[baprs]-"),
    re.compile("-" * 5 + "BEGIN"),
]

CODE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".html", ".css", ".java", ".go", ".rs", ".c", ".cpp", ".h")

# markers of a credential path inside a command line
PATH_TOKENS = [
    re.compile(r"[\\/]secrets[\\/]", I),
    re.compile(r"(^|[\s\\/\"'=])\.env(\.[\w.-]+)?(?=$|[\s\"';|&)])", I),
    re.compile(r"gemini\.json", I),
    re.compile(r"[^\s\\/\"']*_key[^\s\\/\"']*\.md\b", I),
    re.compile(r"desktop[\\/][^\s\"']*?[\\/]?[^\s\\/\"']*token[^\s\\/\"']*", I),
]

DISPLAY = re.compile(
    r"(?<![\w.\-])(cat|type|get-content|gc|head|tail|more|less|echo|write-host|write-output|bat|nl|od|xxd|strings)(?![\w\-])"
    r"|\bprint\s*\("
    r"|(?<![\w.\-])sed\s+-n\b"
    r"|(?<![\w.\-])(py|python3?|python\.exe)(\s+-\d)?\s+-c\b[^\n]*\bopen\s*\("
    r"|\[System\.IO\.File\]::ReadAll",
    I,
)


def deny(msg=REASON):
    try:
        sys.stderr.buffer.write(("[guard_secrets] " + msg + "\n").encode("utf-8"))
        sys.stderr.flush()
    except Exception:
        pass
    sys.exit(2)


def is_secret_path(p):
    p = (p or "").strip().strip('"').replace("/", "\\")
    low = p.lower()
    if "\\secrets\\" in low:
        return True
    base = low.rsplit("\\", 1)[-1]
    if base == ".env" or base.startswith(".env."):
        return True
    if base == "gemini.json":
        return True
    if re.fullmatch(r".*_key.*\.md", base):
        return True
    if "token" in base and "\\desktop\\" in low and not base.endswith(CODE_EXT):
        return True
    return False


def main():
    data = read_payload("guard_secrets")
    if not isinstance(data, dict):
        sys.exit(0)
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict):
        sys.exit(0)
    if tool == "Read":
        fp = ti.get("file_path") or ""
        if isinstance(fp, str) and is_secret_path(fp):
            deny(REASON + ": do not open credential files with Read; let a script read them inside Python")
        sys.exit(0)
    cmd = ti.get("command") or ""
    if not isinstance(cmd, str) or not cmd.strip():
        sys.exit(0)
    for rx in KEY_LITERALS:
        if rx.search(cmd):
            deny(REASON + ": the command contains what looks like a credential literal")
    if any(rx.search(cmd) for rx in PATH_TOKENS) and DISPLAY.search(cmd):
        deny(REASON + ": credential path + display command")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
