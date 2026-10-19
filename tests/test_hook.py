from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TELL = "This serves as a testament to the vibrant tapestry of our evolving landscape."
CLEAN = "Rebased onto main and reran the failing test. The branch is unchanged."


class Case(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.home = os.path.join(self._td.name, "home")
        self.cwd = os.path.join(self._td.name, "cwd")
        os.makedirs(self.home)
        os.makedirs(self.cwd)

    def cfg(self, name, text):
        d = os.path.join(self.home, ".config", "ai-tell-lint")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            f.write(text)

    def raw(self, stdin, env=None):
        e = {"PATH": os.environ["PATH"], "HOME": self.home, "PYTHONPATH": ROOT}
        e.update(env or {})
        return subprocess.run([sys.executable, "-m", "ai_tell_lint.hook"], input=stdin,
                              capture_output=True, text=True, cwd=self.cwd, env=e, timeout=30)

    def run_hook(self, payload, env=None):
        out = self.raw(json.dumps(payload), env).stdout
        if '"deny"' in out:
            return "DENY"
        if '"decision": "block"' in out:
            return "BLOCK"
        return "PASS" if not out.strip() else "OTHER:" + out

    def bash(self, cmd, env=None):
        return self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                              "tool_input": {"command": cmd}, "cwd": self.cwd}, env)

    def write(self, text, env=None, path="docs/a.md"):
        return self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Write",
                              "tool_input": {"file_path": os.path.join(self.cwd, path),
                                             "content": text}, "cwd": self.cwd}, env)

    def stop(self, text, **extra):
        p = {"hook_event_name": "Stop", "last_assistant_message": text, "cwd": self.cwd}
        p.update(extra)
        return self.run_hook(p)


class TestHook(Case):
    def test_heredoc_md_denied(self):
        self.assertEqual(self.bash("cat > notes.md <<'EOF'\n%s\nEOF" % TELL), "DENY")

    def test_gh_pr_body_denied(self):
        self.assertEqual(self.bash('gh pr comment 5 --body "%s"' % TELL), "DENY")

    def test_git_commit_denied(self):
        self.assertEqual(self.bash('git commit -m "%s"' % TELL), "DENY")

    def test_write_md_denied(self):
        self.assertEqual(self.write(TELL), "DENY")

    def test_clean_passes(self):
        self.assertEqual(self.write(CLEAN), "PASS")

    def test_command_prefix_off(self):
        self.assertEqual(self.bash('AI_TELL_LINT=off git commit -m "%s"' % TELL), "PASS")

    def test_env_off(self):
        self.assertEqual(self.write(TELL, env={"AI_TELL_LINT": "off"}), "PASS")

    def test_sentinel_off(self):
        self.cfg("off", "")
        self.assertEqual(self.write(TELL), "PASS")

    def test_stop_off_by_default(self):
        self.assertEqual(self.stop(TELL), "PASS")

    def test_stop_on_when_configured(self):
        self.cfg("config.json", '{"check_replies": true}')
        self.assertEqual(self.stop(TELL), "BLOCK")

    def test_stop_hook_active_no_loop(self):
        self.cfg("config.json", '{"check_replies": true}')
        self.assertEqual(self.stop(TELL, stop_hook_active=True), "PASS")

    def test_broken_config_fails_open(self):
        self.cfg("config.json", "{nope")
        p = self.raw(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Write",
                                 "tool_input": {"file_path": "a.md", "content": TELL}}))
        self.assertEqual((p.returncode, p.stdout.strip()), (0, ""))

    def test_garbage_stdin_fails_open(self):
        p = self.raw("not json")
        self.assertEqual((p.returncode, p.stdout.strip()), (0, ""))

    def test_log_only_when_set(self):
        log = os.path.join(self._td.name, "log")
        self.assertEqual(self.write(TELL, env={"AI_TELL_LINT_LOG": log}), "DENY")
        with open(log) as f:
            self.assertEqual(len(f.read().splitlines()), 1)
        self.assertEqual(self.write(TELL), "DENY")
        self.assertEqual(os.listdir(self.home), [])

    def test_message_has_no_private_names(self):
        out = self.raw(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Write",
                                   "tool_input": {"file_path": "a.md", "content": TELL}})).stdout
        self.assertIn("deny", out)
        for name in ("Omar", "humanizer", "~/.claude/hooks"):
            self.assertNotIn(name, out)


if __name__ == "__main__":
    unittest.main()
