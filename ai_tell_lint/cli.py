from __future__ import annotations

import argparse
import os
import sys

from .config import ConfigError, find_repo_root, load_config
from .core import Hit, lint


def _esc(s: str, prop: bool = False) -> str:
    s = s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return s.replace(":", "%3A").replace(",", "%2C") if prop else s


def format_hit(path: str, hit: Hit, level: str, fmt: str) -> str:
    if fmt == "github":
        loc = "file=%s" % _esc(path, True) + (",line=%d" % hit.line if hit.line is not None else "")
        return "::%s %s::%s" % (level, loc, _esc(str(hit)))
    return "%s%s: %s: %s" % (path, ":%d" % hit.line if hit.line is not None else "", level, hit)


def _err(msg: str) -> int:
    print("ai-tell-lint: " + msg, file=sys.stderr)
    return 2


def _pr_main(argv: list[str]) -> int:
    from . import pr

    p = argparse.ArgumentParser(prog="ai-tell-lint pr")
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--event")
    p.add_argument("--commits", choices=("warn", "block"), default="warn")
    p.add_argument("--config")
    p.add_argument("--format", choices=("text", "github"), default="github")
    a = p.parse_args(argv)
    return pr.run_pr(a.base, a.head, a.event, a.commits, a.config, a.format)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as e:  # an uncaught crash must not look like a block hit (exit 1)
        return _err("internal error: %s" % e)


def _main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "pr":
        return _pr_main(argv[1:])
    p = argparse.ArgumentParser(prog="ai-tell-lint",
                                epilog="Subcommand: 'ai-tell-lint pr --base SHA --head SHA' lints a pull request.")
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
            text, shown = (sys.stdin.buffer.read().decode("utf-8", "replace")
                           if hasattr(sys.stdin, "buffer") else sys.stdin.read()), "<stdin>"
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
