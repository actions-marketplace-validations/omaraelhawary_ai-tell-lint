from __future__ import annotations

import argparse
import os
import sys

from .config import ConfigError, find_repo_root, load_config
from .core import Hit, lint


def format_hit(path: str, hit: Hit, level: str, fmt: str) -> str:
    if fmt == "github":
        loc = "file=%s" % path + (",line=%d" % hit.line if hit.line is not None else "")
        return "::%s %s::%s" % (level, loc, hit)
    return "%s%s: %s: %s" % (path, ":%d" % hit.line if hit.line is not None else "", level, hit)


def _err(msg: str) -> int:
    print("ai-tell-lint: " + msg, file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "pr":
        # Task 6 replaces this stub.
        return _err("pr mode is not implemented yet")
    p = argparse.ArgumentParser(prog="ai-tell-lint")
    p.add_argument("--config")
    p.add_argument("--format", choices=("text", "github"), default="text")
    p.add_argument("files", nargs="*", metavar="FILE")
    args = p.parse_args(argv)
    try:
        rules = load_config(args.config, find_repo_root(os.getcwd()))
    except (ConfigError, OSError, ValueError) as e:
        return _err(str(e))
    failed = False
    for path in args.files or ["-"]:
        if path == "-":
            text, shown = sys.stdin.read(), "<stdin>"
        else:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                return _err("no such file: " + path)
            shown = path
        res = lint(text, rules)
        for level, hits in (("error", res.block), ("warning", res.warn)):
            for h in hits:
                print(format_hit(shown, h, level, args.format))
        failed = failed or bool(res.block)
    return 1 if failed else 0
