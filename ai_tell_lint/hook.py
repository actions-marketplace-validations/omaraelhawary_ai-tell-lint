"""Claude Code hook: lint prose before it ships.

PreToolUse (Bash, Write|Edit|MultiEdit) denies the call; Stop blocks the reply
when the merged config has "check_replies": true. Fails open on any error.
Off switches: env AI_TELL_LINT=off|0|false, a command prefix of the same, or the
file ~/.config/ai-tell-lint/off.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import sys

from . import config, core, extract

# Only a real command prefix counts, never the same text inside a quoted body.
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_OPS = {";", "&&", "||", "|", "&", "|&", ";;"}


def _command_bypass(command: str) -> bool:
    """True if some command segment starts with an AI_TELL_LINT=off style assignment."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        return False
    start = True
    for tok in tokens:
        if tok in _OPS:
            start = True
        elif start and _ASSIGN.match(tok):
            if tok in ("AI_TELL_LINT=off", "AI_TELL_LINT=0", "AI_TELL_LINT=false"):
                return True
        else:
            start = False
    return False
OFF_SENTINEL = "~/.config/ai-tell-lint/off"


def dedupe(items: list) -> list:
    seen, out = set(), []
    for it in items:
        if str(it) not in seen:
            seen.add(str(it))
            out.append(it)
    return out


def reason(block: list, warn: list, what: str) -> str:
    lines = ["Blocked: %s reads like AI-generated text." % what, "", "Must fix:"]
    lines += ["  - %s" % h for h in block[:14]]
    if len(block) > 14:
        lines.append("  - ...and %d more" % (len(block) - 14))
    if warn:
        lines += ["", "Also consider:"]
        lines += ["  - %s" % h for h in warn[:8]]
    lines += [
        "",
        "Rewrite the flagged spans in plain, specific words and retry.",
        "Swapping one word for a synonym defeats the check: change the sentence.",
        "If a flagged word really is the right one, ask the user. Only the user should bypass, once, with AI_TELL_LINT=off <command>.",
    ]
    return "\n".join(lines)


def log_hits(kind: str, what: str, block: list, warn: list) -> None:
    path = os.environ.get("AI_TELL_LINT_LOG")
    if not path:
        return
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.rename(path, path + ".1")
        stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        line = "%s\t%s\t%s\tblock=%s\twarn=%s\n" % (
            stamp, kind, what,
            " | ".join(map(str, block))[:600], " | ".join(map(str, warn))[:300])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


def _emit(obj: dict, stdout) -> None:
    stdout.write(json.dumps(obj))
    stdout.write("\n")


def _run(stdin, stdout) -> None:
    if os.environ.get("AI_TELL_LINT", "").lower() in ("off", "0", "false"):
        return
    if os.path.exists(os.path.expanduser(OFF_SENTINEL)):
        return
    payload = json.load(stdin)
    event = payload.get("hook_event_name")
    cwd = payload.get("cwd") or "."

    if event == "Stop":
        if payload.get("stop_hook_active"):
            return
        cfg = config.load_config(repo_root=config.find_repo_root(cwd))
        if not cfg["check_replies"]:
            return
        res = core.lint(payload.get("last_assistant_message") or "", cfg)
        if res.block:
            log_hits("Stop", "reply", res.block, res.warn)
            _emit({"decision": "block", "reason": reason(res.block, res.warn, "your reply")},
                  stdout)
        return

    if event != "PreToolUse":
        return
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    if tool == "Bash":
        command = ti.get("command") or ""
        if _command_bypass(command):
            return
        targets = extract.bash_targets(command)
        what = "this issue, PR or commit text"
        root_dir = cwd
    elif tool in ("Write", "Edit", "MultiEdit"):
        targets = extract.write_targets(tool, ti)
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        what = os.path.basename(fp) or "this file"
        root_dir = os.path.dirname(fp) or "."
    else:
        return
    if not targets:
        return

    cfg = config.load_config(repo_root=config.find_repo_root(root_dir))
    block, warn = [], []
    for text in targets:
        res = core.lint(text or "", cfg)
        block += res.block
        warn += res.warn
    block, warn = dedupe(block), dedupe(warn)
    if block:
        log_hits(tool, what, block, warn)
        _emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason(block, warn, what),
        }}, stdout)


def main(stdin=sys.stdin, stdout=sys.stdout) -> None:
    try:
        _run(stdin, stdout)
    except Exception:
        pass  # fail open: a broken linter must never block real work


if __name__ == "__main__":
    main()
    sys.exit(0)
