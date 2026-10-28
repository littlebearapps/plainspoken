"""Per-host hook replies (#124, shared with #125)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from plainspoken import hostreply  # noqa: E402


class PreTool(unittest.TestCase):
    def test_warn_shape(self):
        out = hostreply.pre_tool("claude-code", person="one line", model="the note")
        self.assertEqual(out, {"systemMessage": "one line",
                               "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "the note"}})

    def test_deny_and_ask(self):
        out = hostreply.pre_tool("codex", decision="deny", reason="why")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], "why")
        self.assertEqual(hostreply.pre_tool("claude-code", decision="ask", reason="r")["hookSpecificOutput"]
                         ["permissionDecision"], "ask")
        for host in ("codex", "hermes"):
            with self.assertRaises(ValueError):
                hostreply.pre_tool(host, decision="ask", reason="r")
        with self.assertRaises(ValueError):
            hostreply.pre_tool("claude-code", decision="allow")

    def test_nothing_to_say(self):
        self.assertIsNone(hostreply.pre_tool("claude-code"))

    def test_never_rewrites_or_allows(self):
        for host in hostreply.HOSTS:
            for kw in ({"person": "p"}, {"model": "m"}, {"person": "p", "model": "m"},
                       {"decision": "deny", "reason": "r"}):
                text = json.dumps(hostreply.pre_tool(host, **kw))
                for word in ("updatedInput", "allow", "modify"):
                    self.assertNotIn(word, text)

    def test_long_text_is_clipped(self):
        out = hostreply.pre_tool("claude-code", model="x" * 20000)
        self.assertLessEqual(len(out["hookSpecificOutput"]["additionalContext"]), hostreply.LIMIT)

    def test_skill_refs_and_notice(self):
        self.assertEqual(hostreply.skill_ref("codex", "check"), "$plainspoken:check")
        self.assertEqual(hostreply.skill_ref("claude-code", "check"), "/plainspoken:check")
        self.assertEqual(hostreply.skill_ref("hermes", "check"), "plainspoken:check")
        self.assertEqual(hostreply.notice("hi"), {"systemMessage": "hi"})


if __name__ == "__main__":
    unittest.main()
