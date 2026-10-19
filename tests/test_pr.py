from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from ai_tell_lint import pr
from ai_tell_lint.config import load_config

TELL = "This serves as a testament to the vibrant tapestry of our evolving landscape."
CLEAN = "Rebased onto main and reran the failing test. The branch is unchanged."
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


class TestPr(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.home = os.path.join(self._td.name, "home")
        self.repo = os.path.join(self._td.name, "repo")
        os.makedirs(self.home)
        os.makedirs(self.repo)
        old_cwd, old_home = os.getcwd(), os.environ.get("HOME")
        os.environ["HOME"] = self.home
        os.chdir(self.repo)

        def restore():
            os.chdir(old_cwd)
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

        self.addCleanup(restore)
        subprocess.run(["git", "init", "-q"], check=True)

    def write(self, name, text, mode="w"):
        with open(os.path.join(self.repo, name), mode) as f:
            f.write(text)

    def commit(self, msg="c", author=None):
        subprocess.run(["git", "add", "-A"], check=True)
        cmd = GIT + ["commit", "-q", "--allow-empty", "-m", msg]
        if author:
            cmd += ["--author", author]
        subprocess.run(cmd, check=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()

    def run_pr(self, base, head, event=None, level="warn", config=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = pr.run_pr(base, head, event, level, config, "github")
        return rc, out.getvalue(), err.getvalue()

    def event(self, title="Fix", body=""):
        p = os.path.join(self._td.name, "event.json")
        with open(p, "w") as f:
            json.dump({"pull_request": {"title": title, "body": body}}, f)
        return p

    def test_old_text_not_reported(self):
        self.write("README.md", "# T\n\n%s\n" % TELL)
        base = self.commit()
        self.write("README.md", "# T\n\n%s\n\n%s\n" % (TELL, CLEAN))
        head = self.commit()
        rc, out, _ = self.run_pr(base, head)
        self.assertEqual(rc, 0, out)

    def test_added_tell_reported_with_line(self):
        self.write("README.md", "# T\n\n%s\n" % CLEAN)
        base = self.commit()
        self.write("README.md", "# T\n\n%s\n" % TELL)
        head = self.commit()
        rc, out, _ = self.run_pr(base, head)
        self.assertEqual(rc, 1)
        self.assertIn("::error file=README.md,line=3::", out)

    def test_commit_tell_warns_by_default(self):
        base = self.commit("init")
        self.write("a.txt", "x")
        head = self.commit(TELL)
        rc, out, _ = self.run_pr(base, head)
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"::warning .*commit")

    def test_commit_block_option(self):
        base = self.commit("init")
        self.write("a.txt", "x")
        head = self.commit(TELL)
        rc, _, _ = self.run_pr(base, head, level="block")
        self.assertEqual(rc, 1)

    def test_bot_and_merge_commits_skipped(self):
        base = self.commit("init")
        self.write("a.txt", "x")
        head = self.commit(TELL, author="dependabot[bot] <bot@x>")
        self.assertEqual(pr.commit_messages(base, head), [])
        rc, out, _ = self.run_pr(base, head, level="block")
        self.assertEqual(rc, 0, out)

    def test_base_config_wins(self):
        self.write("README.md", "# T\n")
        base = self.commit()
        self.write(".ai-tell-lint.json", json.dumps({"disable": list(load_config(text="{}")["block"])}))
        self.write("README.md", "# T\n\n%s\n" % TELL)
        head = self.commit()
        rc, _, _ = self.run_pr(base, head)
        self.assertEqual(rc, 1)

    def test_missing_base_exit_2(self):
        head = self.commit("init")
        rc, _, err = self.run_pr("0" * 40, head)
        self.assertEqual(rc, 2)
        self.assertIn("fetch-depth: 0", err)

    def test_deleted_and_renamed(self):
        self.write("a.md", "%s\n" % TELL)
        self.write("b.md", "\n".join([CLEAN] * 5) + "\n")
        base = self.commit()
        os.remove(os.path.join(self.repo, "a.md"))
        os.rename(os.path.join(self.repo, "b.md"), os.path.join(self.repo, "c.md"))
        self.write("c.md", "\n".join([CLEAN] * 5 + [TELL]) + "\n")
        head = self.commit()
        rc, out, _ = self.run_pr(base, head)
        self.assertEqual(rc, 1)
        self.assertIn("file=c.md,line=6", out)
        self.assertNotIn("a.md", out)

    def test_spaced_path(self):
        os.makedirs(os.path.join(self.repo, "docs"))
        self.write("docs/a b.md", "# T\n")
        base = self.commit()
        self.write("docs/a b.md", "# T\n\n%s\n" % TELL)
        head = self.commit()
        rc, out, _ = self.run_pr(base, head)
        self.assertEqual(rc, 1)
        self.assertIn("file=docs/a b.md,line=3::", out)

    def test_quoted_path_unquoted(self):
        self.write('q"x.md', "# T\n")
        base = self.commit()
        self.write('q"x.md', "# T\n\n%s\n" % TELL)
        head = self.commit()
        rc, out, _ = self.run_pr(base, head)
        self.assertEqual(rc, 1)
        self.assertIn('file=q"x.md,line=3::', out)

    def test_plusplus_content_line_is_not_a_header(self):
        self.write("x.md", "\n".join([CLEAN] * 10) + "\n")
        base = self.commit()
        lines = [CLEAN] * 10
        lines[1] = "++ x.md"
        lines[7] = TELL
        self.write("x.md", "\n".join(lines) + "\n")
        head = self.commit()
        rc, out, _ = self.run_pr(base, head)
        self.assertEqual(rc, 1)
        self.assertIn("file=x.md,line=8::", out)

    def test_git_failure_exit_2(self):
        base = self.commit("init")
        head = self.commit("next")
        real = pr._git

        def fake(*args):
            if "diff" in args:
                return subprocess.CompletedProcess(args, 128, b"", b"boom")
            return real(*args)

        with mock.patch.object(pr, "_git", fake):
            rc, _, err = self.run_pr(base, head)
        self.assertEqual(rc, 2)
        self.assertIn("ai-tell-lint: git diff failed: boom", err)

    def test_binary_md_no_crash(self):
        base = self.commit("init")
        self.write("x.md", b"\xff\xfe delve", mode="wb")
        head = self.commit()
        self.run_pr(base, head)

    def test_null_body(self):
        base = self.commit("init")
        self.write("a.txt", "x")
        head = self.commit(CLEAN)
        ev = self.event(body=None)
        rc, out, _ = self.run_pr(base, head, event=ev)
        self.assertEqual(rc, 0, out)

    def test_pr_body_tell(self):
        base = self.commit("init")
        self.write("a.txt", "x")
        head = self.commit(CLEAN)
        rc, out, _ = self.run_pr(base, head, event=self.event(body=TELL))
        self.assertEqual(rc, 1)
        self.assertIn("PR description", out)


if __name__ == "__main__":
    unittest.main()
