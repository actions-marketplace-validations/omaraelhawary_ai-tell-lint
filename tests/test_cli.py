from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from ai_tell_lint import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TELL = "This serves as a testament to the vibrant tapestry of our evolving landscape."
CLEAN = "Rebased onto main and reran the failing test. The branch is unchanged."


class TestCli(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.home = os.path.join(self._td.name, "home")
        self.cwd = os.path.join(self._td.name, "cwd")
        os.makedirs(self.home)
        os.makedirs(self.cwd)
        old_cwd, old_home = os.getcwd(), os.environ.get("HOME")
        os.environ["HOME"] = self.home
        os.chdir(self.cwd)

        def restore():
            os.chdir(old_cwd)
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

        self.addCleanup(restore)

    def file(self, name, text):
        with open(os.path.join(self.cwd, name), "w") as f:
            f.write(text)
        return name

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_clean_file_exit_0(self):
        rc, out, _ = self.run_cli([self.file("a.md", CLEAN)])
        self.assertEqual((rc, out), (0, ""))

    def test_tell_file_exit_1(self):
        rc, out, _ = self.run_cli([self.file("a.md", TELL)])
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith("a.md:1: error: AI vocabulary"), out)

    def test_warn_only_exit_0(self):
        from ai_tell_lint import config
        cats = list(config.load_config()["block"])
        cfg = self.file("c.json", json.dumps({"warn_only": cats}))
        rc, out, _ = self.run_cli(["--config", cfg, self.file("a.md", TELL)])
        self.assertEqual(rc, 0)
        self.assertIn("warning", out)

    def test_stdin(self):
        with mock.patch("sys.stdin", io.StringIO(TELL)):
            rc, out, _ = self.run_cli([])
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith("<stdin>:1:"), out)

    def test_dash_reads_stdin(self):
        with mock.patch("sys.stdin", io.StringIO(CLEAN)):
            rc, out, _ = self.run_cli(["-"])
        self.assertEqual((rc, out), (0, ""))

    def test_github_format(self):
        rc, out, _ = self.run_cli(["--format", "github", self.file("a.md", TELL)])
        self.assertTrue(out.startswith("::error file=a.md,line=1::"), out)

    def test_bad_config_exit_2(self):
        cfg = self.file("c.json", json.dumps({"block": {"Mine": ["(unclosed"]}}))
        rc, _, err = self.run_cli(["--config", cfg, self.file("a.md", TELL)])
        self.assertEqual(rc, 2)
        self.assertIn("(unclosed", err)

    def test_missing_file_exit_2(self):
        rc, _, err = self.run_cli(["nope.md"])
        self.assertEqual(rc, 2)
        self.assertIn("ai-tell-lint: no such file: nope.md", err)

    def test_non_prose_file_still_linted(self):
        rc, _, _ = self.run_cli([self.file("a.py", TELL)])
        self.assertEqual(rc, 1)

    def test_pr_requires_base_and_head(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            cli.main(["pr"])
        self.assertEqual(cm.exception.code, 2)

    def test_format_hit(self):
        from ai_tell_lint.core import Hit
        h = Hit("Cat", "snip")
        self.assertEqual(cli.format_hit("p", h, "error", "text"), 'p: error: Cat: "snip"')
        self.assertEqual(cli.format_hit("p", h, "warning", "github"), '::warning file=p::Cat: "snip"')

    def test_python_m_entry(self):
        self.file("a.md", TELL)
        r = subprocess.run([sys.executable, "-m", "ai_tell_lint", "a.md"], capture_output=True,
                           text=True, cwd=self.cwd, timeout=30,
                           env={"PATH": os.environ["PATH"], "HOME": self.home, "PYTHONPATH": ROOT})
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
