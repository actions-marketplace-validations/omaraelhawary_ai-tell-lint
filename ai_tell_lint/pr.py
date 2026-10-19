from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys

from .cli import format_hit
from .config import ConfigError, load_config
from .core import lint
from .extract import is_prose_path

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True)


def _text(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")


def added_lines(base: str, head: str) -> dict[str, set[int]]:
    r = _git("-c", "core.quotepath=off", "diff", "--src-prefix=a/", "--dst-prefix=b/", "-U0", "-M", "--diff-filter=AMR", base, head)
    out: dict[str, set[int]] = {}
    path = None
    for line in _text(r.stdout).splitlines():
        if line.startswith("+++ "):
            path = line[4:] if line[4:] != "/dev/null" else None
            if path and path.startswith("b/"):
                path = path[2:]
            if path and not is_prose_path(path):
                path = None
        elif path:
            m = HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                lines = out.setdefault(path, set())
                lines.update(range(start, start + count))
    return {p: ls for p, ls in out.items() if ls}


def commit_messages(base: str, head: str) -> list[tuple[str, str]]:
    r = _git("log", "--no-merges", "--format=%h%x00%an%x00%B%x1e", "%s..%s" % (base, head))
    msgs = []
    for rec in _text(r.stdout).split("\x1e"):
        if not rec.strip():
            continue
        sha, author, body = (rec.lstrip("\n").split("\x00", 2) + ["", ""])[:3]
        if not author.endswith("[bot]"):
            msgs.append((sha, body.strip()))
    return msgs


def _report(path: str, res, level_block: str, fmt: str, numbered: bool = False) -> bool:
    failed = False
    if not numbered:  # PR text and commit messages have no file lines to annotate
        res.block = [dataclasses.replace(h, line=None) for h in res.block]
        res.warn = [dataclasses.replace(h, line=None) for h in res.warn]
    for h in res.block:
        print(format_hit(path, h, level_block, fmt))
        failed = failed or level_block == "error"
    for h in res.warn:
        print(format_hit(path, h, "warning", fmt))
    return failed


def run_pr(base: str, head: str, event_path: str | None, commits_level: str,
           config_path: str | None, fmt: str) -> int:
    for sha in (base, head):
        if _git("cat-file", "-e", sha + "^{commit}").returncode != 0:
            print("ai-tell-lint: commit %s is not in this clone. "
                  "Set fetch-depth: 0 on actions/checkout." % sha, file=sys.stderr)
            return 2
    try:
        if config_path:
            rules = load_config(config_path)
        else:
            r = _git("show", "%s:.ai-tell-lint.json" % base)
            # No base config: bundled defaults only, never the head copy or user file.
            rules = load_config(text=_text(r.stdout) if r.returncode == 0 else "{}")
        event = {}
        if event_path:
            with open(event_path, encoding="utf-8") as f:
                event = json.load(f)
    except (ConfigError, OSError, ValueError) as e:
        print("ai-tell-lint: %s" % e, file=sys.stderr)
        return 2
    failed = False
    p = event.get("pull_request") or {}
    if p:
        text = "%s\n\n%s" % (p.get("title") or "", p.get("body") or "")
        failed |= _report("PR description", lint(text, rules), "error", fmt)
    level = "error" if commits_level == "block" else "warning"
    for sha, msg in commit_messages(base, head):
        failed |= _report("commit " + sha, lint(msg, rules), level, fmt)
    for path, lines in sorted(added_lines(base, head).items()):
        r = _git("show", "%s:%s" % (head, path))
        if r.returncode != 0:
            continue
        failed |= _report(path, lint(_text(r.stdout), rules, only_lines=lines), "error", fmt, True)
    return 1 if failed else 0
