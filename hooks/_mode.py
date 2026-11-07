"""Mode switch reader. The `mode` file next to this script contains `default` or `work`;
missing / unreadable / unknown -> `default` (no behaviour change).
Used by context-injection hooks (not included in this repo) to stay silent in work mode."""
import os
import sys

MODE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode")


def current_mode() -> str:
    try:
        with open(MODE_FILE, encoding="utf-8") as f:
            m = f.read().strip().lower()
        return m if m in ("default", "work") else "default"
    except Exception:
        return "default"


def exit_if_work():
    """Work mode: drain stdin and exit silently. Default mode: do nothing."""
    if current_mode() != "work":
        return
    try:
        sys.stdin.buffer.read()
    except Exception:
        pass
    sys.exit(0)
