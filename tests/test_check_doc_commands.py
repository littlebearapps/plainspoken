import unittest

from scripts.dev.check_doc_commands import _CALL


class Calls(unittest.TestCase):
    def test_reads_command_words_and_flags(self):
        m = _CALL.search("Run `python3 lib/run.py eval blind build --spec pairs.toml --out blind/ --seed 7`.")
        self.assertEqual((m.group(1), m.group(2).split()[:3]), ("eval", ["blind", "build", "--spec"]))
        m = _CALL.search("pipe it to `RUN check - --plugin-profile 'x'`")
        self.assertEqual((m.group(1), m.group(2).split()), ("check", ["-", "--plugin-profile"]))

    def test_ignores_prose_mentions(self):
        self.assertIsNone(_CALL.search("the runner runs it"))


if __name__ == "__main__":
    unittest.main()
