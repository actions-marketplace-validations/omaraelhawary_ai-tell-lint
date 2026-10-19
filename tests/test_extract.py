from __future__ import annotations

import os
import tempfile
import unittest

from ai_tell_lint import extract

TELL = "This serves as a testament to the vibrant tapestry of our evolving landscape."
CLEAN = "Rebased onto main and reran the failing test. The branch is unchanged."
HEREDOC = "cat > %s <<'EOF'\n" + TELL + "\nEOF"


def bash(cmd):
    return "\n".join(extract.bash_targets(cmd))


class TestExtract(unittest.TestCase):
    def setUp(self):
        self._tmp = []

    def tearDown(self):
        for p in self._tmp:
            try:
                os.remove(p)
            except OSError:
                pass

    def tmpfile(self, text):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self._tmp.append(path)
        return path

    # ported from test-bash-redirect.py: DENY cases must surface the text
    def test_skip_paths_match_relative_and_absolute(self):
        for p in ("node_modules/a.md", "/x/node_modules/a.md", "docs/vendor/a.md"):
            self.assertFalse(extract.is_prose_path(p), p)
        self.assertTrue(extract.is_prose_path("docs/a.md"))

    def test_heredoc_to_md(self):
        self.assertIn(TELL, bash(HEREDOC % "notes.md"))

    def test_heredoc_to_nested_md(self):
        self.assertIn(TELL, bash(HEREDOC % "docs/guide/intro.md"))

    def test_append_to_md(self):
        self.assertIn(TELL, bash("cat >> notes.md <<'EOF'\n" + TELL + "\nEOF"))

    def test_tee_to_md(self):
        self.assertIn(TELL, bash("cat <<'EOF' | tee notes.md\n" + TELL + "\nEOF"))

    def test_echo_to_md(self):
        self.assertIn(TELL, bash('echo "%s" > notes.md' % TELL))

    def test_printf_to_txt(self):
        self.assertIn(TELL, bash("printf '%%s' '%s' > notes.txt" % TELL))

    def test_gh_pr_comment_body(self):
        self.assertIn(TELL, bash('gh pr comment 5 --repo caseproof/memberintel --body "%s"' % TELL))

    def test_git_commit_message(self):
        self.assertIn(TELL, bash('git commit -m "%s"' % TELL))

    # ported PASS cases: the text is either absent or not extracted at all
    def test_heredoc_to_py_is_not_prose(self):
        self.assertNotIn(TELL, bash(HEREDOC % "script.py"))

    def test_heredoc_without_redirect_is_not_extracted(self):
        self.assertNotIn(TELL, bash("cat <<'EOF'\n" + TELL + "\nEOF"))

    def test_clean_prose_to_md_is_extracted_without_tell(self):
        targets = bash("cat > notes.md <<'EOF'\n" + CLEAN + "\nEOF")
        self.assertIn(CLEAN, targets)
        self.assertNotIn(TELL, targets)

    def test_is_prose_path(self):
        self.assertTrue(extract.is_prose_path("docs/a.md"))
        self.assertFalse(extract.is_prose_path("a.py"))
        self.assertFalse(extract.is_prose_path("x/node_modules/a.md"))

    def test_body_file_flag(self):
        path = self.tmpfile(TELL)
        self.assertIn(TELL, bash("gh pr create --body-file %s" % path))

    def test_gh_api_field(self):
        self.assertIn(TELL, bash('gh api repos/o/r/issues/1/comments -f body="%s"' % TELL))

    def test_write_targets(self):
        self.assertEqual(extract.write_targets("Edit", {"file_path": "a.md", "new_string": "x"}), ["x"])
        self.assertEqual(extract.write_targets("Write", {"file_path": "a.py", "content": "x"}), [])


if __name__ == "__main__":
    unittest.main()
