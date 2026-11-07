"""Shared input parsing for the hooks.

Claude Code sends the hook payload as UTF-8 JSON, but on Windows `py.exe` decodes stdin
with the system code page (cp936 on a Chinese-locale machine), which garbles CJK text.
Fix: read raw bytes -> strict UTF-8 decode -> fall back to cp936 -> on failure log and return {}.
stdout is also switched to UTF-8.
"""
import sys, json, io, os, datetime

LOG = os.path.join(os.path.expanduser("~"), ".claude", "logs", "hookio.log")


def _log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


def utf8_stdout():
    """Switch stdout to UTF-8. Do not re-wrap a stream that is already UTF-8: wrapping twice
    closes the underlying buffer ('I/O operation on closed file', observed in practice)."""
    try:
        enc = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
        if enc == "utf8":
            return
        # Force LF: Windows text mode would turn LF into CRLF, and hook output must match byte-for-byte.
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True, newline="\n")
    except Exception:
        pass


def read_payload(caller: str = "?") -> dict:
    """Return the hook JSON payload as a dict; bad input is logged, never raised."""
    utf8_stdout()
    try:
        b = sys.stdin.buffer.read()
    except Exception as e:
        _log(f"{caller} stdin read fail {type(e).__name__}: {e}")
        return {}
    if not b.strip():
        return {}
    raw = None
    try:
        raw = b.decode("utf-8")
    except UnicodeDecodeError:
        try:
            raw = b.decode("cp936")
            _log(f"{caller} stdin was not utf-8, decoded as cp936 ({len(b)} bytes)")
        except UnicodeDecodeError as e:
            _log(f"{caller} stdin undecodable {e}")
            return {}
    try:
        return json.loads(raw)
    except ValueError as e:
        _log(f"{caller} stdin not json: {e}; head={raw[:60]!r}")
        return {}


def prompt_of(payload: dict) -> str:
    return (payload.get("prompt") or "").strip()
