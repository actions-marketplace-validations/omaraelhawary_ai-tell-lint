from __future__ import annotations

import copy
import json
import os
import re
import subprocess

from . import core

USER_CONFIG = "~/.config/ai-tell-lint/config.json"
ALLOWED = {"_readme", "block", "warn", "disable", "warn_only",
           "max_em_dashes_per_150_words", "check_replies"}


class ConfigError(Exception):
    pass


def find_repo_root(path: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError("cannot read %s: %s" % (path, e))


def _check_tier(user: dict, tier: str) -> dict:
    val = user.get(tier, {})
    if not isinstance(val, dict):
        raise ConfigError('"%s" must be an object of category: [patterns]' % tier)
    for cat, pats in val.items():
        if not isinstance(pats, list) or not all(isinstance(p, str) for p in pats):
            raise ConfigError('"%s" in "%s" must be a list of strings' % (cat, tier))
        for p in pats:
            try:
                re.compile(p)
            except re.error as err:
                raise ConfigError('bad pattern in "%s": %s (%s)' % (cat, p, err))
    return val


def _add(dest: dict, cat: str, pats: list) -> None:
    cur = dest.setdefault(cat, [])
    cur.extend(p for p in pats if p not in cur)


def load_config(explicit: str | None = None, repo_root: str | None = None,
                text: str | None = None) -> dict:
    if text is None:
        paths = [explicit] if explicit else (
            ([os.path.join(repo_root, ".ai-tell-lint.json")] if repo_root else [])
            + [os.path.expanduser(USER_CONFIG)])
        for p in paths:
            if explicit or os.path.isfile(p):
                text = _read(p)
                break
    with open(core.DEFAULT_RULES_PATH, encoding="utf-8") as f:
        rules = json.load(f)
    merged = {
        "block": copy.deepcopy(rules.get("block", {})),
        "warn": copy.deepcopy(rules.get("warn", {})),
        "max_em_dashes_per_150_words": rules.get("max_em_dashes_per_150_words", 1),
        "check_replies": False,
    }
    if text is None:
        return merged
    try:
        user = json.loads(text)
    except ValueError as e:
        raise ConfigError("invalid JSON: %s" % e)
    if not isinstance(user, dict):
        raise ConfigError("config must be a JSON object")
    bad = sorted(set(user) - ALLOWED)
    if bad:
        raise ConfigError("unknown config key(s): %s" % ", ".join(bad))
    for tier in ("block", "warn"):
        for cat, pats in _check_tier(user, tier).items():
            _add(merged[tier], cat, pats)
    for key in ("disable", "warn_only"):
        v = user.get(key, [])
        if not isinstance(v, list) or not all(isinstance(c, str) for c in v):
            raise ConfigError('"%s" must be a list of category names' % key)
    for cat in user.get("disable", []):
        merged["block"].pop(cat, None)
        merged["warn"].pop(cat, None)
    for cat in user.get("warn_only", []):
        if cat in merged["block"]:
            _add(merged["warn"], cat, merged["block"].pop(cat))
    if "max_em_dashes_per_150_words" in user:
        n = user["max_em_dashes_per_150_words"]
        if isinstance(n, bool) or not isinstance(n, (int, float)):
            raise ConfigError('"max_em_dashes_per_150_words" must be a number')
        merged["max_em_dashes_per_150_words"] = n
    if "check_replies" in user:
        if not isinstance(user["check_replies"], bool):
            raise ConfigError('"check_replies" must be true or false')
        merged["check_replies"] = user["check_replies"]
    return merged
