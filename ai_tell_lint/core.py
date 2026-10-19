from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

DEFAULT_RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")

MIN_WORDS = 4  # below this a body is bare metadata ("Fixes #123"), not prose


@dataclass(frozen=True)
class Hit:
    category: str
    snippet: str
    line: int | None = None

    def __str__(self) -> str:
        if self.snippet == "":
            return self.category
        return '%s: "%s"' % (self.category, self.snippet)


@dataclass
class Result:
    block: list[Hit] = field(default_factory=list)
    warn: list[Hit] = field(default_factory=list)


def _blank(m: re.Match) -> str:
    n = m.group(0).count("\n")
    return "\n" * n if n else " "


def scrub(text: str) -> str:
    """Drop what a writing rule should not judge, keeping line positions."""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"```.*?```", _blank, text, flags=re.S)
    text = re.sub(r"~~~.*?~~~", _blank, text, flags=re.S)
    text = re.sub(r"<!--.*?-->", _blank, text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", _blank, text)
    text = re.sub(r"<[^>\n]{1,200}>", _blank, text)
    text = re.sub(r"https?://\S+", _blank, text)
    text = re.sub(r"\]\([^)\s]+\)", "] ", text)  # link targets
    text = re.sub(r"^\s*\[[^\]]+\]:\s*\S+$", _blank, text, flags=re.M)
    text = re.sub(r"^---\n.*?\n---\n", _blank, text, flags=re.S)  # yaml frontmatter
    # Note: \s* can eat blank lines before a trailer; _blank keeps their newlines.
    text = re.sub(r"(?m)^\s*(?:Co-Authored-By|Signed-off-by|Refs?|Closes|Fixes):.*$", _blank, text)
    return text


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def _scan(groups: dict, clean: str, only_lines: set[int] | None) -> list[Hit]:
    hits: list[Hit] = []
    seen: set = set()
    for label, patterns in groups.items():
        if label.startswith("_"):
            continue
        for pat in patterns:
            for m in re.finditer(pat, clean, re.I):
                line = clean.count("\n", 0, m.start()) + 1
                if only_lines is not None and line not in only_lines:
                    continue
                snippet = re.sub(r"\s+", " ", m.group(0)).strip()[:90]
                key = (label, snippet.lower())
                if key in seen:
                    continue
                seen.add(key)
                hits.append(Hit(label, snippet, line))
    return hits


def lint(text: str, rules: dict, only_lines: set[int] | None = None) -> Result:
    clean = scrub(text)
    if word_count(clean) < MIN_WORDS:
        return Result([], [])

    block = _scan(rules.get("block", {}), clean, only_lines)
    warn = _scan(rules.get("warn", {}), clean, only_lines)

    if only_lines is None:
        counted = clean
    else:
        counted = "\n".join(l for i, l in enumerate(clean.split("\n"), 1) if i in only_lines)
    per150 = rules.get("max_em_dashes_per_150_words", 1)
    dashes = counted.count("—")
    words = word_count(counted)
    allowed = max(1, int(words / 150.0 * per150))
    if dashes > allowed:
        block.append(Hit("Em-dash overkill: %d em dashes in %d words (limit %d)"
                         % (dashes, words, allowed), "", None))
    return Result(block, warn)
