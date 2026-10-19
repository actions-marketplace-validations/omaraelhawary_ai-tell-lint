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


class GitError(Exception):
    pass


def _git_ok(*args: str) -> bytes:
    r = _git(*args)
    if r.returncode != 0:
        raise GitError("git %s failed: %s" % ("diff" if "diff" in args else args[0], _text(r.stderr).strip()))
    return r.stdout


_ESC = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, "\\": 92, '"': 34}


def _unquote(s: str) -> str:
    """Undo git's C-style quoting of a path (octal bytes and the usual escapes)."""
    raw, i, body = bytearray(), 0, s[1:-1]
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n in "01234567":
                j = i + 1
                while j < len(body) and j < i + 4 and body[j] in "01234567":
                    j += 1
                raw.append(int(body[i + 1:j], 8) & 255)
                i = j
                continue
            raw.append(_ESC.get(n, ord(n)))
            i += 2
            continue
        raw.extend(c.encode("utf-8"))
        i += 1
    return _text(bytes(raw))


def _header_path(rest: str) -> str | None:
    rest = rest.rstrip("\t")  # git appends a tab after names containing spaces
    if rest == "/dev/null":
        return None
    if rest.startswith('"'):
        rest = _unquote(rest)
    return rest[2:] if rest.startswith("b/") else rest


def added_lines(base: str, head: str) -> dict[str, set[int]]:
    out = _git_ok("-c", "core.quotepath=off", "diff", "--src-prefix=a/", "--dst-prefix=b/",
                  "-U0", "-M", "--diff-filter=AMR", base, head)
    res: dict[str, set[int]] = {}
    path, state = None, "start"  # start -> minus -> hunks, reset by each "diff --git"
    for line in _text(out).splitlines():
        if line.startswith("diff --git "):
            path, state = None, "header"
        elif state == "header" and line.startswith("--- "):
            state = "minus"
        elif state == "minus" and line.startswith("+++ "):
            path, state = _header_path(line[4:]), "hunks"
            if path and not is_prose_path(path):
                path = None
        elif state == "hunks" and path:
            m = HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                res.setdefault(path, set()).update(range(start, start + count))
    return {p: ls for p, ls in res.items() if ls}


def commit_messages(base: str, head: str) -> list[tuple[str, str]]:
    out = _git_ok("log", "--no-merges", "--format=%h%x00%an%x00%B%x1e", "%s..%s" % (base, head))
    msgs = []
    for rec in _text(out).split("\x1e"):
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
    try:
        commits = commit_messages(base, head)
        added = added_lines(base, head)
    except GitError as e:
        print("ai-tell-lint: %s" % e, file=sys.stderr)
        return 2
    for sha, msg in commits:
        failed |= _report("commit " + sha, lint(msg, rules), level, fmt)
    for path, lines in sorted(added.items()):
        r = _git("show", "%s:%s" % (head, path))
        if r.returncode != 0:
            continue
        failed |= _report(path, lint(_text(r.stdout), rules, only_lines=lines), "error", fmt, True)
    return 1 if failed else 0
