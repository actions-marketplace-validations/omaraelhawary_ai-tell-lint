import json, os, tempfile, unittest
from ai_tell_lint import config

def write(d, obj):
    p = os.path.join(d, ".ai-tell-lint.json")
    with open(p, "w") as f: json.dump(obj, f)
    return p

class TestConfig(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.environ["HOME"] = self.d   # keeps the real ~/.config out

    def test_defaults(self):
        c = config.load_config(repo_root=self.d)
        self.assertIn("AI vocabulary", c["block"])
        self.assertFalse(c["check_replies"])

    def test_add_pattern_merges(self):
        write(self.d, {"block": {"AI vocabulary": ["\\bsynergy\\b"]}})
        c = config.load_config(repo_root=self.d)
        self.assertIn("\\bsynergy\\b", c["block"]["AI vocabulary"])
        self.assertIn("\\bdelve(s|d|ing)?\\b", c["block"]["AI vocabulary"])

    def test_disable(self):
        write(self.d, {"disable": ["Rule of three"]})
        self.assertNotIn("Rule of three", config.load_config(repo_root=self.d)["warn"])

    def test_warn_only_moves_category(self):
        write(self.d, {"warn_only": ["Puffery"]})
        c = config.load_config(repo_root=self.d)
        self.assertNotIn("Puffery", c["block"])
        self.assertIn("Puffery", c["warn"])

    def test_em_dash_override_and_check_replies(self):
        write(self.d, {"max_em_dashes_per_150_words": 3, "check_replies": True})
        c = config.load_config(repo_root=self.d)
        self.assertEqual(c["max_em_dashes_per_150_words"], 3)
        self.assertTrue(c["check_replies"])

    def test_bad_regex_names_pattern(self):
        write(self.d, {"block": {"Mine": ["(unclosed"]}})
        with self.assertRaises(config.ConfigError) as cm:
            config.load_config(repo_root=self.d)
        self.assertIn("Mine", str(cm.exception))
        self.assertIn("(unclosed", str(cm.exception))

    def test_bad_json(self):
        with open(os.path.join(self.d, ".ai-tell-lint.json"), "w") as f:
            f.write("{nope")
        with self.assertRaises(config.ConfigError):
            config.load_config(repo_root=self.d)

    def test_unknown_key_rejected(self):
        write(self.d, {"disabel": ["Puffery"]})
        with self.assertRaises(config.ConfigError):
            config.load_config(repo_root=self.d)

    def test_text_argument_wins(self):
        write(self.d, {"disable": ["Puffery"]})
        c = config.load_config(repo_root=self.d, text='{"check_replies": true}')
        self.assertIn("Puffery", c["block"])
        self.assertTrue(c["check_replies"])
