# fact_gate.py -- Claude Code Stop hook: a fact-check gate on the assistant's last reply.
# Purpose: if this turn's reply states numbers / dates / past events / current status / quotes of what
#          the user said, and nothing in the recent tool results or the user's own messages supports it,
#          and it is not marked as an unverified impression, bounce the turn once so the agent checks first
#          or rewrites the sentence as "unverified".
# Semantics (checked against code.claude.com/docs/en/hooks): the Stop event's stdin has transcript_path /
#          stop_hook_active / last_assistant_message; printing {"decision":"block","reason":...} with exit 0
#          makes Claude continue, with the reason fed back to it. stop_hook_active=true means this Stop is
#          already the result of a Stop-hook bounce and must be allowed, otherwise it loops.
# Every failure is fail-open. Never prints credentials.
# CLI test: python fact_gate.py --transcript x.jsonl [--text "..."] [--dry] [--active]
#           (--dry prints the verdict JSON only, never the block JSON)
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "logs", "factgate.jsonl")
CWD = os.path.join(HERE, "logs", "gate_cwd")           # empty dir so the child process does not load a project CLAUDE.md
CLAUDE = os.environ.get("FACTGATE_CLAUDE") or shutil.which("claude") or "claude"
MODEL = "claude-haiku-5-5"
BUDGET = float(os.environ.get("FACTGATE_BUDGET", "9"))   # total time budget for one verdict (seconds)
# cli = subscription via `claude -p` (no extra spend); api = paid API credit (off by default)
ROUTES = os.environ.get("FACTGATE_ROUTES", "cli").split(",")
# log = run the full check, only write the log, always allow (default observation mode);
# block = emit a block when unsupported claims are found.
# Precedence: --mode on the command line > FACTGATE_MODE env var > default "log"
MODE = os.environ.get("FACTGATE_MODE", "log").strip().lower()
if "--mode" in sys.argv[1:-1]:
    MODE = sys.argv[sys.argv.index("--mode") + 1].strip().lower()
if MODE not in ("log", "block"):
    MODE = "log"
TAIL_BYTES = 8_000_000
N_TURNS = 6                 # evidence window: since the user's last 6 human messages
EV_CAP_EACH = 1500
EV_CAP_TASK = 2500
EV_CAP_HOOK = 1800
EV_CAP_TOTAL = 12000

# ---------- cheap prefilter: replies without any of these markers pass without a model call ----------
# (tuned for Chinese-language replies; digits match in any language)
PREFILTER = re.compile(
    r"\d"
    r"|[一二三四五六七八九十百千万两]+(?:个|天|次|条|块|U|元|万|月|号|日)"
    r"|昨天|前天|上周|上个月|刚才|昨晚|今早|以前|之前|上次|那次"
    r"|记得|说过|讲过|提过|答应|已经|做完|做过|没做|从来|从没|没有过|确认|核实|查过|查了"
    r"|你(?:原话|说|刚说|那时)|她说|原话"
    r"|[「“\"].{2,60}[」”\"]"
    r"|融资|截止|到期|上线|发布|获奖|奖金|额度|余额|还剩|通过|拒绝|失败|成功"
)

NL_ = chr(10)
TIME_ONLY = re.compile(re.escape("[time-check]") + "[^" + NL_ + "]*(" + NL_ + re.escape("[location]") + "[^" + NL_ + "]*)?")
SKIP_USER_PREFIX = ("[Image:", "<system-reminder>", "<task-notification>", "<local-command", "<command-name>",
                    "<command-message>", "<tools-used", "Caveat:")


def log(rec):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        rec = dict(rec, mode=MODE, at=_dt.datetime.now().isoformat(timespec="seconds"))
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_stdin_json():
    try:
        b = sys.stdin.buffer.read()
    except Exception:
        return {}
    if not b.strip():
        return {}
    for enc in ("utf-8-sig", "cp936"):
        try:
            return json.loads(b.decode(enc))
        except Exception:
            continue
    return {}


# ---------- transcript parsing ----------
def _blocks(msg):
    c = (msg or {}).get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _tr_text(b):
    c = b.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return ""


def load_events(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        off = max(0, size - TAIL_BYTES)
        f.seek(off)
        data = f.read().decode("utf-8", "ignore")
    lines = data.splitlines()
    if off > 0 and lines:
        lines = lines[1:]                       # first line may be a truncated half line
    evs = []
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("{") or ln[:40].startswith(('{"type":"api-request', '{"type": "api-request')):
            continue                            # api-request(-blob) lines are large and useless; skip
        try:
            evs.append(json.loads(ln))
        except Exception:
            continue
    return evs


def is_real_user(o):
    if o.get("type") != "user" or o.get("isMeta") or o.get("isSidechain"):
        return False
    texts = [b.get("text", "") for b in _blocks(o.get("message")) if b.get("type") == "text"]
    if not texts:
        return _has_image(o) and (o.get("origin") or {}).get("kind") == "human"   # image-only message
    return not texts[0].lstrip().startswith(SKIP_USER_PREFIX)


def _has_image(o):
    return any(b.get("type") == "image" for b in _blocks(o.get("message")))


def _user_text(o):
    return "\n".join(b.get("text", "") for b in _blocks(o.get("message")) if b.get("type") == "text")


def analyse(evs, last_text_hint=""):
    """Return (assistant_text, evidence_text).
    Evidence window = since the user's last N_TURNS human messages: the agent's tool calls, tool results,
    subagent notifications, hook-injected context (UserPromptSubmit memory/time blocks, isMeta
    system-reminder text), plus the user's last messages and an "user sent images" marker.
    Capped at EV_CAP_TOTAL, newest first.
    A memory block only proves "the memory store records this", not that the event happened;
    the criteria say so."""
    evs = [e for e in evs if e.get("type") in ("user", "assistant", "attachment") and not e.get("isSidechain")]
    real_idx = [i for i, e in enumerate(evs) if e.get("type") == "user" and is_real_user(e)]
    a_text = (last_text_hint or "").strip()
    if not a_text:
        for e in reversed(evs):
            if e.get("type") == "assistant":
                t = "\n".join(b.get("text", "") for b in _blocks(e.get("message")) if b.get("type") == "text").strip()
                if t:
                    a_text = t
                    break
    if not real_idx:
        return a_text, "(no user message found)"[:EV_CAP_TOTAL]
    win = real_idx[-N_TURNS:]
    start = win[0]
    # which turn each event belongs to (0 = this turn, 1 = previous turn, ...)
    age_of = {}
    for k, i in enumerate(win):
        nxt = win[k + 1] if k + 1 < len(win) else len(evs)
        for j in range(i, nxt):
            age_of[j] = len(win) - 1 - k
    items = []          # (age, label, text) in time order
    seen = set()
    img_ages = []
    for j in range(start, len(evs)):
        e = evs[j]
        age = age_of.get(j, 0)
        ty_e = e.get("type")
        if ty_e == "attachment":
            a = e.get("attachment") or {}
            if a.get("type") == "hook_success" and a.get("hookEvent") in ("UserPromptSubmit", "SessionStart", "PostToolUse"):
                c = (a.get("content") or a.get("stdout") or "").strip()
                if age > 0 and TIME_ONLY.fullmatch(c.replace(chr(13), "")):
                    continue                    # time/location-only lines from older turns carry no information
                if len(c) > 12 and c not in seen:
                    seen.add(c)
                    items.append((age, "hook-injected", c[:EV_CAP_HOOK]))
            continue
        if ty_e == "user" and j in real_idx:
            if _has_image(e):
                img_ages.append(age)
            continue
        if ty_e == "user" and e.get("isMeta"):
            t = _user_text(e).strip()
            if len(t) > 12 and not t.startswith("[Image:") and t not in seen:
                seen.add(t)
                items.append((age, "system-injected", t[:EV_CAP_HOOK]))
            continue
        for b in _blocks(e.get("message")):
            ty = b.get("type")
            if ty_e == "assistant" and ty == "tool_use":
                inp = json.dumps(b.get("input", {}), ensure_ascii=False)[:250]
                items.append((age, "agent-call", f"{b.get('name')} {inp}"))
            elif ty_e == "user" and ty == "tool_result":
                t = _tr_text(b)
                if t.strip():
                    items.append((age, "tool-result", t[:EV_CAP_EACH]))
            elif ty_e == "user" and ty == "text" and b.get("text", "").lstrip().startswith("<task-notification>"):
                items.append((age, "subagent-notification", b["text"][:EV_CAP_TASK]))
    user_msgs = []
    for i in win:
        user_msgs.append("\n".join(b.get("text", "") for b in _blocks(evs[i].get("message")) if b.get("type") == "text")[:600])
    user_part = "[User's last %d messages (valid evidence for what the user said), old -> new]\n" % len(user_msgs) + "\n---\n".join(user_msgs)
    if img_ages:
        user_part += "\n\n[User sent images] " + ", ".join("this turn" if a == 0 else f"{a} turns ago" for a in sorted(set(img_ages))) + \
                    ": the user sent images (you cannot see them); descriptions of image content in the reply count as supported, do not report them."
    budget = EV_CAP_TOTAL - len(user_part) - 120
    out, used = [], 0
    for age, label, t in reversed(items):          # newest first
        line = f"[{'this turn' if age == 0 else f'{age} turns ago'} | {label}] {t}"
        if used + len(line) + 1 > budget:
            if budget - used > 300:
                line = line[: budget - used - 1]
            else:
                break
        out.append(line)
        used += len(line) + 1
    ev = user_part + "\n\n[Tool / subagent / hook-injected evidence (last %d turns, new -> old)]\n" % len(win) + ("\n".join(out) if out else "(none)")
    return a_text, ev[:EV_CAP_TOTAL]


# ---------- ask Haiku: `claude -p` on the subscription, optional paid API fallback ----------
CRITERIA = """You are a fact-check gate. The "reply" below is what an AI assistant just said to its user. The "evidence" is what the assistant actually retrieved in the last few turns (tool results, subagent reports, hook-injected context such as memory blocks and time), plus the user's recent messages.
List the factual claims in the reply that have NO support in the evidence AND are NOT marked as an impression / unverified / guess. Only these kinds:
1 numbers (amounts, counts, scores, quotas, dates, deadlines, durations)
2 past events (who did what, who earned what, what happened, whether something exists -- especially universal negatives like "never" / "has not")
3 current status (done or not, live or not, passed or not, how much is left)
4 quoting or paraphrasing what the user said or did (quotation marks count)
5 facts about specific external entities (whether a company raised money, when a product shipped, what a rule says)
Counts as supported: directly found in the evidence (any of the recent turns, not only this one) or directly computable from it; the user's own words support claims about what the user said; a memory block supports "the memory store records this" (only for external facts and for things the assistant itself did); when the evidence says the user sent images, descriptions of image content are not reported.
[Hard rule: assigned != done] For claims about what the USER did or said ("I reminded you", "you did / practised / submitted", "you said"), only two kinds of evidence count: the user's own words in a user message, or an image the user sent.
Plans, push notifications, homework assignments, schedules, calendars, plan-file entries, and memory notes that only say "assigned / pending / pushed / sent" do NOT support such claims -- they prove something was assigned or sent, not that the user did or said it.
If such a claim only has that kind of evidence, you MUST report it (type=quote-user, why="only push/assignment records, no words from the user"); "when in doubt, don't report" does not apply here.
Counts as marked: the same sentence or paragraph explicitly says it is an impression / unverified / a guess (e.g. "this is my impression, unverified", "I think", "probably", "not checked", or Chinese markers such as 这是我印象 / 没核 / 印象 / 我猜 / 猜的 / 大概 / 好像 / 没查).
Do NOT report: feelings / emotions / casual conversation, opinions and judgements, plans for the future, questions, plans made on the spot, restatements and summaries of the evidence, common knowledge, plain instructions.
Also do not report: descriptive or emotional language in casual conversation or fictional examples; general linguistic knowledge (grammar, word meaning, usage) unless it gives a concrete checkable fact (date, number, official rule).
Bias: when in doubt, do not report. Report at most 4; each claim is a quote of at most 40 characters from the reply.
Output exactly one line of JSON and nothing else: {"unsupported":[{"claim":"quoted excerpt","type":"number|date|past-event|status|quote-user|external-fact","why":"one sentence: what the evidence lacks"}]}. If everything is supported output {"unsupported":[]}"""


def build_prompt(a_text, ev):
    return (CRITERIA + f"\n\nNow: {_dt.datetime.now():%Y-%m-%d %H:%M} (local time)\n\n===== evidence =====\n{ev}\n"
            f"===== reply =====\n{a_text[:4000]}\n===== end =====")


def _parse(out):
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        raise ValueError("no json")
    d = json.loads(m.group(0))
    res = []
    for it in (d.get("unsupported") or [])[:4]:
        if isinstance(it, dict) and it.get("claim"):
            res.append({"claim": str(it["claim"])[:80], "type": str(it.get("type", ""))[:10],
                        "why": str(it.get("why", ""))[:80]})
    return res


def _via_cli(prompt, timeout):
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    env["FACTGATE_CHILD"] = "1"          # if the child process also fires a Stop hook, it passes straight through (no recursion)
    os.makedirs(CWD, exist_ok=True)
    r = subprocess.run([CLAUDE, "-p", "--model", MODEL, "--setting-sources", "project", "--strict-mcp-config",
                        "--tools", "", "--no-session-persistence", "--output-format", "text",
                        "--system-prompt", "You are a strict JSON-only classifier. Output one line of JSON."],
                       input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=CWD, env=env, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        tail = re.sub(r"\s+", " ", (r.stderr or r.stdout or "")[-120:]).strip()
        raise RuntimeError(f"cli rc={r.returncode} {tail}")
    return _parse(r.stdout)


def _via_api(prompt, timeout):
    key = os.environ["FACTGATE_API_KEY"]   # read from the environment only; never printed or logged
    body = json.dumps({"model": MODEL, "max_tokens": 400,
                       "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    return _parse("".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"))


def ask_model(prompt):
    t0 = time.time()
    errs = []
    for name in ROUTES:
        left = BUDGET - (time.time() - t0)
        if left < 1.5:
            errs.append("budget")
            break
        for attempt in (1, 2):              # fast failure (rc != 0) with time left: retry once
            left = BUDGET - (time.time() - t0)
            if left < 3:
                break
            try:
                return (_via_cli if name == "cli" else _via_api)(prompt, left), name, ""
            except Exception as e:
                fast = (time.time() - t0) < 3
                errs.append(f"{name}:{type(e).__name__}:{str(e)[:100]}")
                if not (isinstance(e, RuntimeError) and fast):
                    break
    return None, "none", ",".join(errs)


def make_reason(claims):
    lines = [f"{i}. \"{c['claim']}\" ({c['type']}) - {c['why']}" for i, c in enumerate(claims, 1)]
    return ("Fact gate: your last reply contains these claims, with no support in this turn's tool results "
            "or the user's messages, and they are not marked as an impression:\n"
            + "\n".join(lines)
            + "\nChoose one: (1) check now with tools (search memory / read files / query status) and rewrite with "
              "what you found; (2) if it cannot be checked, rewrite with \"this is my impression, unverified\" in front "
              "of that sentence. Send only the corrected version; do not apologise for the bounce.")


def run(payload, text_override=""):
    t0 = time.time()
    if os.environ.get("FACTGATE_CHILD") == "1":
        return None, "child"
    if payload.get("stop_hook_active"):                 # block at most once, never loop
        log({"verdict": "pass", "why": "stop_hook_active"})
        return None, "stop_hook_active"
    tp = payload.get("transcript_path") or ""
    hint = text_override or payload.get("last_assistant_message") or ""
    if not tp or not os.path.exists(tp):
        return None, "no_transcript"
    a_text, ev = analyse(load_events(tp), hint)
    if len(a_text) < 12 or not PREFILTER.search(a_text):
        log({"verdict": "pass", "why": "prefilter", "len": len(a_text), "secs": round(time.time() - t0, 2)})
        return None, "prefilter"
    claims, route, err = ask_model(build_prompt(a_text, ev))
    secs = round(time.time() - t0, 1)
    if claims is None:
        log({"verdict": "pass", "why": "gate_error", "err": err, "secs": secs})
        return None, "gate_error:" + err
    if not claims:
        log({"verdict": "pass", "why": "model_clean", "route": route, "secs": secs})
        return None, "model_clean"
    log({"verdict": "block", "route": route, "secs": secs, "claims": claims, "reply_head": a_text[:120]})
    return make_reason(claims), "block"


def main():
    try:
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    a = sys.argv[1:]
    dry = "--dry" in a
    try:
        if "--transcript" in a:
            payload = {"transcript_path": a[a.index("--transcript") + 1], "stop_hook_active": "--active" in a}
        else:
            payload = read_stdin_json()
        txt = a[a.index("--text") + 1] if "--text" in a else ""
        reason, why = run(payload, txt)
    except Exception as e:           # fail-open
        log({"verdict": "pass", "why": "exception", "err": type(e).__name__})
        return 0
    if dry:
        print(json.dumps({"outcome": why, "block": bool(reason), "reason": reason}, ensure_ascii=False))
        return 0
    if reason and MODE == "block":
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
