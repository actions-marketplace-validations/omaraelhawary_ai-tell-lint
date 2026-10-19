import json, unittest
from ai_tell_lint import core

RULES = json.load(open(core.DEFAULT_RULES_PATH, encoding="utf-8"))
FENCE = "`" * 3
TELL = "This serves as a testament to the vibrant tapestry of our evolving landscape."
CLEAN = "Rebased onto main and reran the failing test. The branch is unchanged."

class TestLint(unittest.TestCase):
    def test_tell_blocks(self):
        cats = {h.category for h in core.lint(TELL, RULES).block}
        self.assertIn("AI vocabulary", cats)

    def test_clean_passes(self):
        self.assertEqual(core.lint(CLEAN, RULES).block, [])

    def test_short_text_is_metadata(self):
        self.assertEqual(core.lint("delve tapestry", RULES).block, [])

    def test_code_is_ignored(self):
        text = "Run the script below to see output.\n%s\ndelve tapestry\n%s\nThat is all." % (FENCE, FENCE)
        self.assertEqual(core.lint(text, RULES).block, [])

    def test_line_numbers_survive_fences(self):
        text = "First line is fine and plain.\n%s\na\nb\n%s\nWe delve into it here today." % (FENCE, FENCE)
        hit = [h for h in core.lint(text, RULES).block if "delve" in h.snippet.lower()][0]
        self.assertEqual(hit.line, 6)

    def test_crlf_line_numbers(self):
        text = "Plain words on line one.\r\nPlain words on line two.\r\nWe delve here now."
        self.assertEqual(core.lint(text, RULES).block[0].line, 3)

    def test_only_lines_filters(self):
        text = "We delve on line one today.\nPlain words on line two here."
        self.assertEqual(core.lint(text, RULES, only_lines={2}).block, [])

    def test_em_dash_limit(self):
        text = "One — two — three words here and more words to pass the floor."
        r = core.lint(text, RULES)
        self.assertTrue(any(h.category.startswith("Em-dash overkill") for h in r.block))

    def test_em_dash_counts_only_selected_lines(self):
        text = "Old line — with — dashes — here.\nNew plain line with enough words."
        r = core.lint(text, RULES, only_lines={2})
        self.assertFalse(any(h.category.startswith("Em-dash") for h in r.block))

    def test_hit_str(self):
        self.assertEqual(str(core.Hit("AI vocabulary", "delve", 1)), 'AI vocabulary: "delve"')
