from __future__ import annotations

import os
import re
import shlex

PROSE_EXT = (".md", ".mdx", ".markdown", ".txt", ".rst")
SKIP_PATH = ("/node_modules/", "/vendor/", "/dist/", "/build/", "/.git/",
             "/.claude/", "/coverage/", "/languages/", "/__snapshots__/")

BODY_FLAGS = {"--body", "-b", "--title", "-t", "--message", "-m", "--notes", "--subject"}
FILE_FLAGS = {"--body-file", "-F", "--notes-file"}

PUBLISH_CMD = re.compile(
    r"\bgh\s+(?:issue|pr|release|gist)\s+"
    r"(?:create|comment|edit|review|reply|new)\b"
    r"|\bgh\s+api\b"
    r"|\bgit\s+commit\b",
    re.I,
)

# `cat > notes.md <<EOF` writes the same file as the Write tool and used to walk
# straight past this gate, because bash_targets only looked at publishing
# commands. Watched live on 2026-09-08: told to write prose that trips four
# rules, a model hit the Write deny, switched to a heredoc, and the file landed.
REDIRECT_PROSE = re.compile(r"""(?:>>?|\|\s*tee(?:\s+-a)?)\s*['"]?([^\s'";&|<>]+)""")


def heredocs(command):
    out = []
    for m in re.finditer(r"<<-?\s*['\"]?(\w+)['\"]?\s*\n(.*?)\n\s*\1\b", command, re.S):
        out.append(m.group(2))
    return out


def redirect_targets(command):
    """Text this command writes into a prose file through the shell."""
    if not any(is_prose_path(m.group(1)) for m in REDIRECT_PROSE.finditer(command)):
        return []
    # A heredoc carries the body verbatim. Anything else (echo, printf, a pipe
    # from another command) has no body to isolate, so the command line itself
    # is what gets scanned: a rule only fires on a word that is really there.
    return heredocs(command) or [command]


def bash_targets(command):
    """Pull the human-facing strings out of a shell command."""
    texts = redirect_targets(command)
    if not PUBLISH_CMD.search(command):
        return texts
    texts += list(heredocs(command))
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        tokens = re.findall(r'"([^"]{4,})"|\'([^\']{4,})\'', command)
        tokens = [a or b for a, b in tokens]
        return texts + tokens

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in BODY_FLAGS and i + 1 < len(tokens):
            texts.append(tokens[i + 1])
            i += 2
            continue
        if tok in FILE_FLAGS and i + 1 < len(tokens):
            path = tokens[i + 1]
            if path not in ("-",) and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        texts.append(fh.read())
                except OSError:
                    pass
            i += 2
            continue
        m = re.match(r"^--(?:body|title|message|notes|subject)=(.*)$", tok, re.S)
        if m:
            texts.append(m.group(1))
            i += 1
            continue
        m = re.match(r"^(?:body|title)=(.*)$", tok, re.S)  # gh api -f body=...
        if m and not m.group(1).startswith("@"):
            texts.append(m.group(1))
            i += 1
            continue
        i += 1
    return texts


def is_prose_path(path):
    low = (path or "").lower()
    if not low.endswith(PROSE_EXT):
        return False
    return not any(part in low for part in SKIP_PATH)


def write_targets(tool, ti):
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not is_prose_path(path):
        return []
    if tool == "Write":
        return [ti.get("content") or ""]
    if tool == "Edit":
        return [ti.get("new_string") or ""]
    if tool == "MultiEdit":
        return [e.get("new_string") or "" for e in ti.get("edits") or []]
    return []
