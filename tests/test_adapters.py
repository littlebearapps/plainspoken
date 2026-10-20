"""The proposal adapters (`file`, `github`, `trello`) and `kaizen decisions`. Fakes only: no network,
no real `gh`. The plugin never writes an APPROVE: line itself; a person does, and `kaizen decisions` records it."""
import contextlib
import inspect
import io
import json
import os
import stat
import sys
import urllib.parse
from datetime import timedelta
from pathlib import Path
from unittest import mock

from plainspoken import adapters, calibrate, ledger, proposals
from tests.test_calibrate import CFG, NOW, TmpCase, cli, fp_events, ts

TOKEN = "tok-5ecr3t-value-0123456789abcdef"
KEY = "key-5ecr3t-value-fedcba9876543210"
CARD = "demoCard0001xyz"


def decisions(settings, pid):
    return [e for e in ledger.read(settings)[0] if e["event"] == "decision" and e.get("proposal") == pid]


ADVERSARIAL = {  # the round-2 re-review's shapes (markdown-it renders each as hidden or code)
 "list-item fence": "- ```\n  APPROVE: in code\n  ```",
 "ordered list fence": "1. ~~~\n   APPROVE: in code\n   ~~~",
 "fence info string with comment": "```<!---->\nAPPROVE: in code\n```",
 "fence info string with void tag": "```<br>\n\nAPPROVE: in code\n```",
 "fence after autolink paragraph": "<https://example.com>\n```\n\nAPPROVE: in code\n```",
 "fence after inline-html paragraph": "<b>x</b>\n```\n\nAPPROVE: in code\n```",
 "fence interrupting lazy quote": "> q\n```\n\nAPPROVE: in code\n```",
 "closing fence + NBSP": "```\n``` \nAPPROVE: in code\n```",
 "closing fence + ideographic space": "```\n```　\nAPPROVE: in code\n```",
 "U+2028 inside fence": "```\nx ```\nAPPROVE: in code\n```",
 "form feed inside fence": "```\nx\x0c```\nAPPROVE: in code\n```",
 "U+2028 inside code span": "`x APPROVE: in code`",
 "details closed by inline-code tag": "<details>\n\n`</details>`\n\nAPPROVE: hidden\n\n</details>",
 "details closed by escaped tag": "<details>\n\n\\</details>\n\nAPPROVE: hidden\n\n</details>",
 "self-closing details": "<details/>\n\nAPPROVE: hidden",
 "multi-line open tag": "<details\n>\n\nAPPROVE: hidden\n\n</details>",
 "processing instruction block": "<?x\n\nAPPROVE: hidden\n?>",
 "declaration block": "<!X\n\nAPPROVE: hidden\n>",
 "CDATA block": "<![CDATA[\n\nAPPROVE: hidden\n]]>",
 "inline processing instruction": "text <?\nAPPROVE: hidden\n?>",
 "link ref def title": "[a]: /url\n\"t\nAPPROVE: hidden\"",
 "quote inside list, lazy": "- > q\nAPPROVE: in quote",
 # controls expected not to count
 "setext heading": "APPROVE: heading\n---",
 "zero-width before": "​APPROVE: zw",
 "tab indent": "\tAPPROVE: tab",
 "nested fence 4/3": "````\n```\nAPPROVE: in code\n```\n````",
 "tilde vs backtick": "~~~\n```\nAPPROVE: in code\n~~~",
 "indented code block": "para\n\n    APPROVE: code",
 "lazy para continuation 4sp": "para\n    APPROVE: visible lazy",
 "details multi blank": "<details>\n<summary>s</summary>\n\nAPPROVE: hidden\n\n</details>",
 "html comment multi": "<!--\n\nAPPROVE: hidden\n\n-->",
 "table row": "| a |\n| - |\nAPPROVE: in table",
}


class Base(TmpCase):
    def proposal(self):
        c = self.cands(fp_events())[0]
        p = calibrate.materialise(c, None, CFG, None, [], NOW)
        proposals.save(p, self.settings)
        return p

    def github_settings(self, **gh):
        return {**self.settings, "adapter": "github", "approvers": ["robinlee"],
                "github": {"repo": "acme/rules", "labels": ["kaizen", "ruleset"], **gh}}

    def trello_settings(self, **tr):
        return {**self.settings, "adapter": "trello", "approvers": ["robin"],
                "trello": {"list_id": "demoList0001xyz", "label_ids": ["l1", "l2"],
                           "key_env": "TRELLO_API_KEY", "token_env": "TRELLO_TOKEN", **tr}}


class Grammar(Base):
    """A comment is a decision only when its whole body is one plain line."""

    def test_valid_decisions(self):
        for text, want in (("APPROVE: Robin: matches the v4 decision", ("approved", "Robin: matches the v4 decision")),
                           ("REJECT: too broad (see rule 7)", ("rejected", "too broad (see rule 7)")),
                           ("APPROVE: Zoë: fine", ("approved", "Zoë: fine")),
                           ("  APPROVE: trailing whitespace stripped  \r\n\n", ("approved",
                                                                              "trailing whitespace stripped")),
                           ("\n   REJECT: 50% too strict, per @robin; ok?",
                            ("rejected", "50% too strict, per @robin; ok?")),
                           ("APPROVE: e = mc2 / a + b - c, \"quoted\" 'too'!",
                            ("approved", "e = mc2 / a + b - c, \"quoted\" 'too'!"))):
            self.assertEqual(adapters.parse_decision(text), want, text)

    def test_anything_else_is_not_a_decision(self):
        for text in ("approve: fine", "Approve: fine", "APPROVED: close but no", "I'd say APPROVE: later in the line",
                     "APPROVE:fine", "APPROVE:", "APPROVE: ", "APPROVE:  ", "> APPROVE: quoted",
                     "APPROVE: fine *really*", "APPROVE: see `x`", "APPROVE: fine\nREJECT: second line",
                     "APPROVE: fine\nthanks", "Looks right.\nAPPROVE: second line", "APPROVE: a <b>tag</b>",
                     "APPROVE: a [link](x)", "APPROVE: under_score", "APPROVE: hash #1", "APPROVE: a | b",
                     "APPROVE: a & b", "APPROVE: back\\slash", "APPROVE: tilde ~", "APPROVE: tab\tinside",
                     "APPROVE: zero\u200bwidth", "APPROVE: rtl\u202eoverride", "APPROVE: line\u2028sep",
                     "APPROVE: para\u2029sep", "APPROVE: nbsp\u00a0space", "APPROVE: cr\rinside",
                     "APPROVE: form\x0cfeed", "APPROVE: emoji :smile: shortcode", "\u200bAPPROVE: zero-width first",
                     "APPROVE: " + "x" * 300, "\tAPPROVE: tab indent", "    APPROVE: four spaces"):
            self.assertIsNone(adapters.parse_decision(text), repr(text))

    def test_adversarial_shapes_from_the_review(self):
        for name, text in ADVERSARIAL.items():
            self.assertIsNone(adapters.parse_decision(text), name)

    def test_file_name_split(self):
        self.assertEqual(adapters.file.split_name("Robin: matches the v4 decision"),
                         ("Robin", "matches the v4 decision"))
        self.assertEqual(adapters.file.split_name("reason only"), (None, "reason only"))
        self.assertEqual(adapters.file.split_name("Robin:"), ("Robin", ""))


class FileAdapter(Base):
    def md(self, p) -> Path:
        return self.root / ".plainspoken" / "kaizen" / "proposals" / f"{p['id']}.md"

    def emit(self, p):
        ref = adapters.get(self.settings).emit_proposal(p)
        p["ref"], p["adapter"] = ref, "file"
        proposals.save(p, self.settings)
        return ref

    def test_emit_writes_the_md_with_diff_and_instructions(self):
        p = self.proposal()
        ref = self.emit(p)
        self.assertEqual(ref, f".plainspoken/kaizen/proposals/{p['id']}.md")
        text = self.md(p).read_text(encoding="utf-8")
        self.assertIn(p["summary"], text)
        self.assertIn("```diff\n", text)
        self.assertIn(p["diff"].strip().splitlines()[-1], text)
        self.assertIn("APPROVE: <your name>: <reason>", text)
        self.assertIn(adapters.file.MARKER, text)
        # the template's own example lines don't count as decisions
        self.assertEqual(adapters.get(self.settings).read_decisions(p), [])

    def test_approve_then_reject_latest_counts(self):
        p = self.proposal()
        self.emit(p)
        with self.md(p).open("a", encoding="utf-8") as f:
            f.write("APPROVE: Robin: matches the v4 decision\n")
        lines, errors = adapters.record_decisions(self.settings, NOW)
        self.assertEqual(errors, [])
        self.assertEqual(lines, [f"{p['id']} approved by Robin: matches the v4 decision"])
        got = decisions(self.settings, p["id"])
        self.assertEqual(len(got), 1)
        e = got[0]
        self.assertEqual((e["outcome"], e["actor"], e["facets"], e["reason"], e["rule"]),
                         ("approved", "human", {"by": "Robin"}, "matches the v4 decision", p["rule"]))
        # running again logs nothing new
        self.assertEqual(adapters.record_decisions(self.settings, NOW + timedelta(minutes=1)), ([], []))
        self.assertEqual(len(decisions(self.settings, p["id"])), 1)
        # a later REJECT (still not applied) is the latest decision
        with self.md(p).open("a", encoding="utf-8") as f:
            f.write("REJECT: Sam: too broad after all\n")
        lines, _ = adapters.record_decisions(self.settings, NOW + timedelta(minutes=2))
        self.assertEqual(lines, [f"{p['id']} rejected by Sam: too broad after all"])
        events = ledger.read(self.settings)[0]
        self.assertEqual(proposals.status(p["id"], events), "rejected")
        self.assertEqual(adapters.record_decisions(self.settings, NOW + timedelta(minutes=3)), ([], []))
        self.assertEqual(len(decisions(self.settings, p["id"])), 2)

    def test_same_run_approve_then_reject(self):
        p = self.proposal()
        self.emit(p)
        with self.md(p).open("a", encoding="utf-8") as f:
            f.write("APPROVE: Robin: yes\n\nREJECT: Robin: no, wait\n")  # blank lines between are fine
        self.assertEqual(adapters.record_decisions(self.settings, NOW)[1], [])
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "rejected")

    def test_lower_case_is_not_a_decision_so_the_block_is_refused(self):
        p = self.proposal()
        self.emit(p)
        with self.md(p).open("a", encoding="utf-8") as f:
            f.write("approve: Robin: fine\n")
        lines, errors = adapters.record_decisions(self.settings, NOW)
        self.assertEqual(lines, [])
        self.assertEqual(errors, [f"{p['id']}: the decision block has a line that isn't a plain decision "
                                  f"(line {self.marker_line(p) + 1}) — fix it"])
        self.assertEqual(decisions(self.settings, p["id"]), [])

    def marker_line(self, p) -> int:
        """The 1-based line number of the marker in the proposal's `.md`."""
        return self.md(p).read_text(encoding="utf-8").split("\n").index(adapters.file.MARKER) + 1

    def test_one_colon_is_by_file(self):
        p = self.proposal()
        self.emit(p)
        with self.md(p).open("a", encoding="utf-8") as f:
            f.write("APPROVE: reason only\n")
        adapters.record_decisions(self.settings, NOW)
        e = decisions(self.settings, p["id"])[0]
        self.assertEqual((e["facets"]["by"], e["reason"]), ("file", "reason only"))

    def test_approvers_named_means_only_they_count(self):
        settings = {**self.settings, "approvers": ["Robin"]}
        p = self.proposal()
        self.emit(p)
        with self.md(p).open("a", encoding="utf-8") as f:
            f.write("APPROVE: Mallory: sure\nAPPROVE: no name given\nAPPROVE: robin: case-insensitive\n")
        adapters.record_decisions(settings, NOW)
        got = decisions(settings, p["id"])
        self.assertEqual([e["facets"]["by"] for e in got], ["robin"])

    def test_reemit_keeps_decision_lines(self):
        p = self.proposal()
        self.emit(p)
        with self.md(p).open("a", encoding="utf-8") as f:
            f.write("APPROVE: Robin: keep me\n")
        adapters.get(self.settings).emit_proposal(p)
        self.assertIn("APPROVE: Robin: keep me", self.md(p).read_text(encoding="utf-8"))

    def test_missing_marker_is_an_adapter_failure(self):
        p = self.proposal()
        self.emit(p)
        self.md(p).write_text("APPROVE: Robin: no marker any more\n", encoding="utf-8")
        lines, errors = adapters.record_decisions(self.settings, NOW)
        self.assertEqual(lines, [])
        self.assertEqual(len(errors), 1)
        self.assertIn(p["id"], errors[0])
        self.assertEqual(decisions(self.settings, p["id"]), [])

    def test_applied_proposals_are_not_read(self):
        p = self.proposal()
        self.emit(p)
        ledger.append(ledger.make_event(event="apply", actor="engine", outcome="applied", ruleset_version=CFG.version,
                                        profile="default", rule=p["rule"], proposal=p["id"], ts=ts(NOW)),
                      self.settings)
        with self.md(p).open("a", encoding="utf-8") as f:
            f.write("REJECT: Robin: too late\n")
        self.assertEqual(adapters.record_decisions(self.settings, NOW), ([], []))


class FakeRunner:
    def __init__(self, replies=None):
        self.calls, self.bodies = [], []
        self.replies = list(replies or [])

    def __call__(self, args):
        self.calls.append(list(args))
        if "--body-file" in args:
            self.bodies.append(Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8"))
        return self.replies.pop(0) if self.replies else (0, "", "")


def comments(*items, pid=None, issue="12", body=None, **extra):
    """`gh issue view --json body,comments` output; `pid` puts the plugin's own `**<id>**` line in the issue body."""
    return json.dumps({"body": body if body is not None else (f"**{pid}**: a proposal" if pid else ""),
                       "comments": [{"author": {"login": who}, "body": text, "createdAt": at,
                                     "url": f"https://github.com/acme/rules/issues/{issue}#issuecomment-{n}",
                                     "includesCreatedEdit": False, "isMinimized": False, **extra}
                                    for n, (who, text, at) in enumerate(items)]})


class GitHub(Base):
    def test_create_args_and_ref(self):
        p = self.proposal()
        run = FakeRunner([(0, "Creating issue in acme/rules\n\nhttps://github.com/acme/rules/issues/12\n", "")])
        ref = adapters.get(self.github_settings(), runner=run).emit_proposal(p)
        self.assertEqual(ref, "12")
        args = run.calls[0]
        self.assertEqual(args[:3], ["gh", "issue", "create"])
        self.assertEqual(args[args.index("--repo") + 1], "acme/rules")
        labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
        self.assertEqual(labels, ["kaizen", "ruleset"])
        title = args[args.index("--title") + 1]
        self.assertTrue(title.startswith(f"[kaizen] {p['rule']}: "), title)
        self.assertLessEqual(len(title), adapters.github.TITLE_MAX)
        self.assertIn(p["id"], run.bodies[0])
        self.assertIn("```diff", run.bodies[0])
        self.assertIn("APPROVE:", run.bodies[0])
        self.assertFalse(Path(args[args.index("--body-file") + 1]).exists())  # the temp body is removed

    def test_no_repo_is_a_clear_error(self):
        with self.assertRaises(adapters.AdapterError) as cm:
            adapters.get(self.github_settings(repo=None), runner=FakeRunner())
        self.assertIn("[kaizen.github] repo", str(cm.exception))

    def test_non_approver_comment_is_ignored(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        proposals.save(p, self.settings)
        run = FakeRunner([(0, comments(("mallory", "APPROVE: ship it", "2026-10-14T08:00:00Z"),
                                       ("RobinLee", "APPROVE: matches the v4 decision",
                                        "2026-10-14T09:30:00Z"), pid=p["id"]), "")])
        lines, errors = adapters.record_decisions(self.github_settings(), NOW, runner=run)
        self.assertEqual(errors, [])
        self.assertEqual(run.calls[0], ["gh", "issue", "view", "12", "--repo", "acme/rules", "--json", "body,comments"])
        self.assertEqual(lines, [f"{p['id']} approved by RobinLee: matches the v4 decision"])
        got = decisions(self.settings, p["id"])
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["facets"]["by"], got[0]["ts"]), ("RobinLee", "2026-10-14T09:30:00+00:00"))
        # the same comment read again is not logged again
        run = FakeRunner([(0, comments(("RobinLee", "APPROVE: matches the v4 decision",
                                        "2026-10-14T09:30:00Z"), pid=p["id"]), "")])
        self.assertEqual(adapters.record_decisions(self.github_settings(), NOW, runner=run), ([], []))

    def test_gh_failure_exits_one_and_logs_nothing(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        proposals.save(p, self.settings)
        run = FakeRunner([(1, "", "HTTP 404: Not Found (https://api.github.com/repos/acme/rules/issues/12)\n")])
        lines, errors = adapters.record_decisions(self.github_settings(), NOW, runner=run)
        self.assertEqual(lines, [])
        self.assertEqual(len(errors), 1)
        self.assertIn(p["id"], errors[0])
        self.assertIn("gh", errors[0])
        self.assertEqual(decisions(self.settings, p["id"]), [])

    def test_create_failure_raises(self):
        p = self.proposal()
        with self.assertRaises(adapters.AdapterError):
            adapters.get(self.github_settings(), runner=FakeRunner([(1, "", "label not found\n")])).emit_proposal(p)
        with self.assertRaises(adapters.AdapterError):  # no issue URL in the output
            adapters.get(self.github_settings(), runner=FakeRunner([(0, "done\n", "")])).emit_proposal(p)

    def test_cli_exit_one_with_a_failing_gh_on_path(self):
        (self.root / ".plainspoken").mkdir(exist_ok=True)
        (self.root / ".plainspoken" / "config.toml").write_text(
            '[kaizen]\nadapter = "github"\napprovers = ["robinlee"]\n[kaizen.github]\nrepo = "acme/rules"\n',
            encoding="utf-8")
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        proposals.save(p, self.settings)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.write('gh: authentication required\\n')\n"
                      "sys.exit(4)\n", encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        r = cli("kaizen", "decisions", cwd=self.root, env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(p["id"], r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(decisions(self.settings, p["id"]), [])


class FakeOpener:
    def __init__(self, replies=None, error=None):
        self.requests = []
        self.replies = list(replies or [])
        self.error = error

    def __call__(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.replies.pop(0) if self.replies else (200, b"{}")


ENV = {"TRELLO_API_KEY": KEY, "TRELLO_TOKEN": TOKEN}
MEMBER = "0f" * 12  # a Trello member id (24 hex), built so the source holds no id-shaped literal


def action(text, user, date, card_id=CARD, member="2d" * 12, **data):
    return {"type": "commentCard", "date": date, "idMemberCreator": member,
            "data": {"text": text, "card": {"id": card_id}, **data},
            "memberCreator": {"id": member, "username": user}}


def card(p, desc=None):
    return 200, json.dumps({"id": CARD, "desc": desc if desc is not None else f"**{p['id']}**: a proposal"}).encode()


class Trello(Base):
    def test_post_carries_list_and_labels(self):
        p = self.proposal()
        op = FakeOpener([(200, json.dumps({"id": CARD, "shortUrl": "https://trello.com/c/abc"}).encode())])
        ref = adapters.get(self.trello_settings(), opener=op, env=ENV).emit_proposal(p)
        self.assertEqual(ref, CARD)
        req = op.requests[0]
        self.assertEqual(req.get_method(), "POST")
        url = urllib.parse.urlsplit(req.full_url)
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "api.trello.com", "/1/cards"))
        query = urllib.parse.parse_qs(url.query)
        self.assertEqual((query["key"], query["token"]), ([KEY], [TOKEN]))
        form = urllib.parse.parse_qs(req.data.decode())
        self.assertEqual(form["idList"], ["demoList0001xyz"])
        self.assertEqual(form["idLabels"], ["l1,l2"])
        self.assertIn(p["id"], form["desc"][0])
        self.assertNotIn(TOKEN, req.data.decode())

    def test_401_never_shows_the_token(self):
        p = self.proposal()
        op = FakeOpener([(401, f"invalid token {TOKEN}".encode())])
        with self.assertRaises(adapters.AdapterError) as cm:
            adapters.get(self.trello_settings(), opener=op, env=ENV).emit_proposal(p)
        text = str(cm.exception)
        self.assertIn("401", text)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(KEY, text)
        self.assertIsNone(cm.exception.__cause__)
        self.assertIsNone(cm.exception.__context__)

    def test_network_error_with_the_url_never_shows_the_token(self):
        p = self.proposal()
        err = OSError(f"can't reach https://api.trello.com/1/cards?key={KEY}&token={TOKEN}")
        with self.assertRaises(adapters.AdapterError) as cm:
            adapters.get(self.trello_settings(), opener=FakeOpener(error=err), env=ENV).emit_proposal(p)
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        self.assertTrue(cm.exception.__suppress_context__)  # raised `from None`: the URL never reaches a traceback

    def test_missing_env_var_is_named(self):
        with self.assertRaises(adapters.AdapterError) as cm:
            adapters.get(self.trello_settings(), opener=FakeOpener(), env={"TRELLO_API_KEY": KEY})
        self.assertIn("TRELLO_TOKEN", str(cm.exception))
        self.assertNotIn(KEY, str(cm.exception))
        with self.assertRaises(adapters.AdapterError) as cm:
            adapters.get(self.trello_settings(list_id=None), opener=FakeOpener(), env=ENV)
        self.assertIn("[kaizen.trello] list_id", str(cm.exception))

    def test_read_decisions_keeps_approvers_oldest_first(self):
        p = {**self.proposal(), "ref": CARD, "adapter": "trello"}
        proposals.save(p, self.settings)
        actions = [  # Trello lists actions newest first
            action("REJECT: changed my mind", "robin", "2026-10-14T10:00:00.000Z"),
            action("APPROVE: fine", "mallory", "2026-10-14T09:00:00.000Z"),
            action("APPROVE: first look", "robin", "2026-10-14T08:00:00.000Z"),
        ]
        op = FakeOpener([card(p), (200, json.dumps(actions).encode())])
        lines, errors = adapters.record_decisions(self.trello_settings(), NOW, opener=op, env=ENV)
        self.assertEqual(errors, [])
        self.assertEqual(urllib.parse.urlsplit(op.requests[0].full_url).path, f"/1/cards/{CARD}")
        url = urllib.parse.urlsplit(op.requests[1].full_url)
        self.assertEqual(url.path, f"/1/cards/{CARD}/actions")
        self.assertEqual(urllib.parse.parse_qs(url.query)["filter"], ["commentCard"])
        self.assertEqual(lines, [f"{p['id']} approved by robin: first look",
                                 f"{p['id']} rejected by robin: changed my mind"])
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "rejected")
        for path in (self.root / ".plainspoken").rglob("*"):
            if path.is_file():
                data = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn(TOKEN, data, path)
                self.assertNotIn(KEY, data, path)


class Calibrate(Base):
    def test_file_adapter_writes_the_md_next_to_the_json(self):
        self.write_ledger(fp_events())
        out = calibrate.run(self.root, self.settings, NOW, [])
        self.assertEqual(len(out), 1)
        p = out[0]
        folder = self.root / ".plainspoken" / "kaizen" / "proposals"
        self.assertTrue((folder / f"{p['id']}.json").is_file())
        self.assertTrue((folder / f"{p['id']}.md").is_file())
        stored = proposals.load(p["id"], self.settings)
        self.assertEqual((stored["adapter"], stored["ref"]), ("file", f".plainspoken/kaizen/proposals/{p['id']}.md"))

    def test_github_emit_stores_the_ref(self):
        self.write_ledger(fp_events())
        settings = self.github_settings()
        run = FakeRunner([(0, "https://github.com/acme/rules/issues/7\n", "")])
        out = calibrate.run(self.root, settings, NOW, [], adapter=adapters.get(settings, runner=run))
        self.assertEqual(proposals.load(out[0]["id"], self.settings)["ref"], "7")

    def test_emit_failure_keeps_the_proposal_without_a_ref(self):
        self.write_ledger(fp_events())
        settings = self.github_settings(repo=None)
        out = calibrate.run(self.root, settings, NOW, [])
        self.assertEqual(len(out), 1)
        stored = proposals.load(out[0]["id"], self.settings)
        self.assertNotIn("ref", stored)
        self.assertIn("[kaizen.github] repo", stored["emit_error"])
        # `kaizen decisions` never sends: no gh call, one "not yet sent" line, exit-0 shape
        run = FakeRunner([(0, "https://github.com/acme/rules/issues/9\n", "")])
        lines, errors = adapters.record_decisions(self.github_settings(), NOW, runner=run)
        self.assertEqual(errors, [])
        self.assertEqual(run.calls, [])
        self.assertEqual(lines, ["kaizen decisions: 1 proposal not yet sent — run `kaizen calibrate`"])
        self.assertNotIn("ref", proposals.load(out[0]["id"], self.settings))
        # the next calibrate sends it, even though it has no new candidates
        settings = self.github_settings()
        resent = []
        again = calibrate.run(self.root, settings, NOW, [], adapter=adapters.get(settings, runner=run),
                              resent=resent)
        self.assertEqual(again, [])
        self.assertEqual([x["id"] for x in resent], [out[0]["id"]])
        self.assertEqual(run.calls[0][:3], ["gh", "issue", "create"])
        stored = proposals.load(out[0]["id"], self.settings)
        self.assertEqual(stored["ref"], "9")
        self.assertNotIn("emit_error", stored)

    def test_sent_but_not_saved_names_the_ref_and_stays_exit_zero(self):
        from plainspoken import __main__ as cli_main
        self.write_ledger(fp_events())
        settings = self.github_settings()
        run = FakeRunner([(0, "https://github.com/acme/rules/issues/7\n", "")])
        real = proposals.save

        def save(p, s):
            if p.get("ref"):
                raise OSError("disk full")
            return real(p, s)

        with mock.patch.object(adapters.proposals, "save", save):
            out = calibrate.run(self.root, settings, NOW, [], adapter=adapters.get(settings, runner=run))
        self.assertEqual(len(out), 1)
        self.assertIn("github #7", out[0]["save_error"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            cli_main._emit_note(out[0])
        self.assertEqual(len(err.getvalue().splitlines()), 1)
        self.assertIn("github #7", err.getvalue())

    def test_cli_calibrate_names_the_adapter(self):
        self.write_ledger(fp_events())
        r = cli("kaizen", "calibrate", "--now", ts(NOW), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("emitted to file .plainspoken/kaizen/proposals/", r.stdout)

    def test_cli_calibrate_emit_failure_stays_exit_zero(self):
        (self.root / ".plainspoken").mkdir(exist_ok=True)
        (self.root / ".plainspoken" / "config.toml").write_text(
            '[kaizen]\nadapter = "trello"\napprovers = ["robin"]\n[kaizen.trello]\nlist_id = "abc"\n',
            encoding="utf-8")
        self.write_ledger(fp_events())
        r = cli("kaizen", "calibrate", "--now", ts(NOW), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("TRELLO_API_KEY", r.stderr)
        self.assertIn("not emitted", r.stdout)


class DecisionsCli(Base):
    def test_cli_logs_and_prints(self):
        p = self.proposal()
        adapters.get(self.settings).emit_proposal(p)
        p.update(ref=f".plainspoken/kaizen/proposals/{p['id']}.md", adapter="file")
        proposals.save(p, self.settings)
        md = self.root / p["ref"]
        with md.open("a", encoding="utf-8") as f:
            f.write("APPROVE: Robin: matches the v4 decision\n")
        r = cli("kaizen", "decisions", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{p['id']} approved by Robin", r.stdout)
        r = cli("kaizen", "decisions", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no new decisions", r.stdout)
        self.assertEqual(len(decisions(self.settings, p["id"])), 1)
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "approved")

    def test_cli_trello_missing_env_exits_one_naming_the_var(self):
        (self.root / ".plainspoken").mkdir(exist_ok=True)
        (self.root / ".plainspoken" / "config.toml").write_text(
            '[kaizen]\nadapter = "trello"\napprovers = ["robin"]\n[kaizen.trello]\nlist_id = "abc"\n',
            encoding="utf-8")
        p = {**self.proposal(), "ref": CARD, "adapter": "trello"}
        proposals.save(p, self.settings)
        r = cli("kaizen", "decisions", cwd=self.root, env={"TRELLO_API_KEY": KEY})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("TRELLO_TOKEN", r.stderr)
        self.assertNotIn(KEY, r.stderr + r.stdout)
        self.assertEqual(decisions(self.settings, p["id"]), [])


class Hardening(Base):
    """Scrub-then-cut, and the authorisation checks on what may count as a decision."""

    def test_trello_secret_straddling_the_cut_leaves_no_prefix(self):
        p = self.proposal()
        prefix = "Trello card create failed (HTTP 500): "
        for pad in range(100, 121):  # every cut position inside the token
            body = ("x" * pad + TOKEN + " tail").encode()
            with self.assertRaises(adapters.AdapterError) as cm:
                adapters.get(self.trello_settings(), opener=FakeOpener([(500, body)]), env=ENV).emit_proposal(p)
            text = str(cm.exception)
            self.assertTrue(text.startswith(prefix), text)
            for n in range(6, len(TOKEN) + 1):
                self.assertNotIn(TOKEN[:n], text, (pad, n))

    def test_github_token_straddling_the_cut_leaves_no_prefix(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        secret = "ghp_" + "Z9" * 18
        with mock.patch.dict(os.environ, {"GH_TOKEN": secret}):
            run = FakeRunner([(1, "", "y" * 190 + secret + "\n")])
            with self.assertRaises(adapters.AdapterError) as cm:
                adapters.get(self.github_settings(), runner=run).read_decisions(p)
        self.assertNotIn(secret[:8], str(cm.exception))

    def gh_read(self, p, **kw):
        out = comments(("RobinLee", "APPROVE: fine", "2026-10-14T09:00:00Z"), pid=p["id"], **kw)
        return adapters.get(self.github_settings(), runner=FakeRunner([(0, out, "")])).read_decisions(p)

    def test_github_edited_and_minimised_comments_dont_count(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        self.assertEqual(len(self.gh_read(p)), 1)
        self.assertEqual(self.gh_read(p, includesCreatedEdit=True), [])
        self.assertEqual(self.gh_read(p, isMinimized=True), [])

    def test_github_login_case_insensitive(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        out = comments(("ROBINLEE", "APPROVE: fine", "2026-10-14T09:00:00Z"), pid=p["id"])
        got = adapters.get(self.github_settings(), runner=FakeRunner([(0, out, "")])).read_decisions(p)
        self.assertEqual([d["by"] for d in got], ["ROBINLEE"])

    def test_github_issue_body_never_counts(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        out = comments(body=f"**{p['id']}**: a proposal\nAPPROVE: written into the body")
        got = adapters.get(self.github_settings(), runner=FakeRunner([(0, out, "")])).read_decisions(p)
        self.assertEqual(got, [])

    def test_github_issue_for_another_proposal_is_refused(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}  # a ref pointed at another proposal's issue
        out = comments(("RobinLee", "APPROVE: fine", "2026-10-14T09:00:00Z"), pid="KZ-20261001-abcdef")
        with self.assertRaises(adapters.AdapterError) as cm:
            adapters.get(self.github_settings(), runner=FakeRunner([(0, out, "")])).read_decisions(p)
        self.assertIn("isn't the one made for", str(cm.exception))
        proposals.save(p, self.settings)
        lines, errors = adapters.record_decisions(self.github_settings(), NOW, runner=FakeRunner([(0, out, "")]))
        self.assertEqual((lines, len(errors)), ([], 1))
        self.assertEqual(decisions(self.settings, p["id"]), [])

    def test_github_comment_from_another_issue_doesnt_count(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        out = comments(("RobinLee", "APPROVE: fine", "2026-10-14T09:00:00Z"), pid=p["id"], issue="13")
        self.assertEqual(adapters.get(self.github_settings(), runner=FakeRunner([(0, out, "")])).read_decisions(p),
                         [])

    def trello_read(self, p, acts, desc=None, settings=None):
        op = FakeOpener([card(p, desc), (200, json.dumps(acts).encode())])
        return adapters.get(settings or self.trello_settings(), opener=op, env=ENV).read_decisions(p)

    def test_trello_edited_and_other_card_comments_dont_count(self):
        p = {**self.proposal(), "ref": CARD, "adapter": "trello"}
        ok = action("APPROVE: fine", "robin", "2026-10-14T09:00:00.000Z")
        self.assertEqual(len(self.trello_read(p, [ok])), 1)
        edited = action("APPROVE: fine", "robin", "2026-10-14T09:00:00.000Z", dateLastEdited="2026-10-14T10:00Z")
        self.assertEqual(self.trello_read(p, [edited]), [])
        other = action("APPROVE: fine", "robin", "2026-10-14T09:00:00.000Z", card_id="otherCard0002xyz")
        self.assertEqual(self.trello_read(p, [other]), [])

    def test_trello_card_for_another_proposal_is_refused(self):
        p = {**self.proposal(), "ref": CARD, "adapter": "trello"}
        with self.assertRaises(adapters.AdapterError) as cm:
            self.trello_read(p, [action("APPROVE: fine", "robin", "2026-10-14T09:00:00.000Z")],
                             desc="**KZ-20261001-abcdef**: another")
        self.assertIn("isn't the one made for", str(cm.exception))

    def test_trello_member_id_approver_matches_the_id_not_the_username(self):
        p = {**self.proposal(), "ref": CARD, "adapter": "trello"}
        settings = {**self.trello_settings(), "approvers": [MEMBER]}
        renamed = action("APPROVE: fine", "robin-renamed", "2026-10-14T09:00:00.000Z", member=MEMBER)
        self.assertEqual([d["by"] for d in self.trello_read(p, [renamed], settings=settings)], ["robin-renamed"])
        impostor = action("APPROVE: fine", MEMBER, "2026-10-14T09:00:00.000Z", member="1e" * 12)
        self.assertEqual(self.trello_read(p, [impostor], settings=settings), [])


class Round2(Base):
    """No parser differential (a line counts only if it is certainly visible plain text), and the
    edited/hidden checks fail closed."""

    def test_file_adapter_applies_the_strict_rule_to_every_line(self):
        """Each of these lines, on its own below the marker, is refused."""
        p = self.proposal()
        adapters.get(self.settings).emit_proposal(p)
        md = self.root / ".plainspoken" / "kaizen" / "proposals" / f"{p['id']}.md"
        clean = md.read_text(encoding="utf-8")
        for bad in ("    APPROVE: Robin: four are code", "<!-- APPROVE: Robin: hidden -->",
                    "APPROVE: Robin: *formatted*", "APPROVE: Robin: a\u2028REJECT: Robin: split"):
            md.write_text(clean + bad + "\n", encoding="utf-8")
            with self.assertRaises(adapters.AdapterError, msg=bad):
                adapters.get(self.settings).read_decisions(p)
        md.write_text(clean + "  APPROVE: Robin: two spaces are fine\nREJECT: Robin: plain\n", encoding="utf-8")
        got = adapters.get(self.settings).read_decisions(p)
        self.assertEqual([(d["verdict"], d["reason"]) for d in got],
                         [("approved", "two spaces are fine"), ("rejected", "plain")])

    def test_old_gh_without_edit_flags_fails_closed_with_one_note(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        proposals.save(p, self.settings)
        data = json.loads(comments(("RobinLee", "APPROVE: fine", "2026-10-14T09:00:00Z"),
                                   ("RobinLee", "REJECT: no", "2026-10-14T10:00:00Z"), pid=p["id"]))
        for c in data["comments"]:
            del c["includesCreatedEdit"]
        del data["comments"][1]["isMinimized"]
        run = FakeRunner([(0, json.dumps(data), "")])
        lines, errors = adapters.record_decisions(self.github_settings(), NOW, runner=run)
        self.assertEqual(errors, [])
        self.assertEqual(lines, ["kaizen decisions: 2 comments skipped: gh didn't say whether they were edited "
                                 "— upgrade gh"])
        self.assertEqual(decisions(self.settings, p["id"]), [])

    def test_trello_action_missing_its_frame_fails_closed(self):
        p = {**self.proposal(), "ref": CARD, "adapter": "trello"}
        proposals.save(p, self.settings)
        bare = action("APPROVE: fine", "robin", "2026-10-14T09:00:00.000Z")
        del bare["idMemberCreator"]
        undated = action("APPROVE: fine", "robin", "")
        op = FakeOpener([card(p), (200, json.dumps([bare, undated]).encode())])
        lines, errors = adapters.record_decisions(self.trello_settings(), NOW, opener=op, env=ENV)
        self.assertEqual(errors, [])
        self.assertEqual(lines, ["kaizen decisions: 2 comments skipped: Trello didn't send enough to tell whether "
                                 "they were edited"])
        self.assertEqual(decisions(self.settings, p["id"]), [])


HIDDEN_BLOCKS = {  # the round-3 re-review's file shapes: (lines below the marker, offset of the first line at fault)
 "multi-line html comment": (("<!--", "APPROVE: Robin: hidden", "-->"), 1),
 "details": (("<details>", "", "APPROVE: Robin: collapsed", "", "</details>"), 1),
 "fence": (("```", "APPROVE: Robin: in code", "```"), 1),
 "lazy quote": (("> q", "APPROVE: Robin: in quote"), 1),
 "setext": (("APPROVE: Robin: heading", "---"), 2),
 "table": (("| a |", "| - |", "APPROVE: Robin: cell"), 1),
}


class Round4(Base):
    """The file block is all or nothing, render-safe typographic punctuation and a readable reason,
    one repost note for near misses, and one INSTRUCTION text."""

    def md(self, p) -> Path:
        return self.root / ".plainspoken" / "kaizen" / "proposals" / f"{p['id']}.md"

    def emit(self, p):
        p["ref"], p["adapter"] = adapters.get(self.settings).emit_proposal(p), "file"
        proposals.save(p, self.settings)
        return self.md(p).read_text(encoding="utf-8")

    def refused(self, p, line: int) -> str:
        return f"{p['id']}: the decision block has a line that isn't a plain decision (line {line}) — fix it"

    def test_hidden_block_shapes_count_nothing_and_name_the_line(self):
        p = self.proposal()
        clean = self.emit(p)
        marker = clean.split("\n").index(adapters.file.MARKER) + 1
        for name, (block, at) in HIDDEN_BLOCKS.items():
            self.md(p).write_text(clean + "\n".join(block) + "\n", encoding="utf-8")
            lines, errors = adapters.record_decisions(self.settings, NOW)
            self.assertEqual(lines, [], name)
            self.assertEqual(errors, [self.refused(p, marker + at)], name)
            self.assertEqual(decisions(self.settings, p["id"]), [], name)

    def test_a_block_of_two_valid_lines_still_works_latest_wins(self):
        p = self.proposal()
        clean = self.emit(p)
        self.md(p).write_text(clean + "APPROVE: Robin: yes\n\nREJECT: Sam: no, too broad\n", encoding="utf-8")
        lines, errors = adapters.record_decisions(self.settings, NOW)
        self.assertEqual(errors, [])
        self.assertEqual(lines, [f"{p['id']} approved by Robin: yes", f"{p['id']} rejected by Sam: no, too broad"])
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "rejected")

    def test_text_on_the_marker_line_itself_is_refused(self):
        p = self.proposal()
        clean = self.emit(p)
        marker = clean.split("\n").index(adapters.file.MARKER) + 1
        self.md(p).write_text(clean.replace(adapters.file.MARKER, adapters.file.MARKER + " APPROVE: Robin: tail"),
                              encoding="utf-8")
        self.assertEqual(adapters.record_decisions(self.settings, NOW), ([], [self.refused(p, marker)]))

    def test_cli_exits_one_for_the_bad_block_and_still_processes_the_rest(self):
        bad = self.proposal()
        clean = self.emit(bad)
        marker = clean.split("\n").index(adapters.file.MARKER) + 1
        self.md(bad).write_text(clean + "> q\nAPPROVE: Robin: in quote\n", encoding="utf-8")
        good = {**bad, "id": bad["id"][:-6] + "abcdef"}
        proposals.save(good, self.settings)
        self.emit(good)
        with self.md(good).open("a", encoding="utf-8") as f:
            f.write("APPROVE: Robin: fine\n")
        r = cli("kaizen", "decisions", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(self.refused(bad, marker + 1), r.stderr)
        self.assertIn(f"{good['id']} approved by Robin: fine", r.stdout)
        self.assertEqual(decisions(self.settings, bad["id"]), [])
        self.assertEqual(len(decisions(self.settings, good["id"])), 1)

    def test_typographic_punctuation_counts(self):
        for text, want in (("APPROVE: it’s fine — matches v4…", ("approved", "it’s fine — matches v4…")),
                           ("REJECT: “no” – ‘not yet’", ("rejected", "“no” – ‘not yet’")),
                           ("APPROVE: Robin: it’s fine", ("approved", "Robin: it’s fine"))):
            self.assertEqual(adapters.parse_decision(text), want, text)
        self.assertEqual(adapters.file.split_name("Robin: it’s fine"), ("Robin", "it’s fine"))

    def test_reason_must_show_a_letter_or_digit_and_marks_are_capped(self):
        grave = "̀"
        for text in ("APPROVE: ㅤ", "APPROVE: ᅟᅠ", "APPROVE: ﾠ", "APPROVE: ㅤ – …",
                     "APPROVE: . , ; !", "APPROVE: a" + grave * 200, "APPROVE: a" + grave * 4,
                     "APPROVE: " + grave * 3, "APPROVE: ͏", "APPROVE: ️"):
            self.assertIsNone(adapters.parse_decision(text), repr(text))
        for text in ("APPROVE: a" + grave * 3, "APPROVE: é", "APPROVE: ㅤ ok", "APPROVE: 7", "APPROVE: Việt ổn"):
            self.assertIsNotNone(adapters.parse_decision(text), repr(text))

    def test_keycaps_and_overlay_strikes_dont_count(self):  # they render as an emoji or struck-out text
        for text in ("APPROVE: 1️⃣", "APPROVE: 1⃣ fine", "APPROVE: ok️", "APPROVE: s̶h̶i̶p̶ it",
                     "APPROVE: n̸o̸", "APPROVE: fine⃝", "APPROVE: no󠄀"):
            self.assertIsNone(adapters.parse_decision(text), repr(text))

    def test_github_near_misses_from_approvers_get_one_repost_note(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        proposals.save(p, self.settings)
        out = comments(("RobinLee", "APPROVE: fine *really*", "2026-10-14T09:00:00Z"),
                       ("mallory", "APPROVE: *not an approver*", "2026-10-14T09:01:00Z"),
                       ("RobinLee", "Looks right to me.", "2026-10-14T09:02:00Z"), pid=p["id"])
        lines, errors = adapters.record_decisions(self.github_settings(), NOW, runner=FakeRunner([(0, out, "")]))
        self.assertEqual(errors, [])
        self.assertEqual(lines, [f"kaizen decisions: 1 comment looks like a decision but isn't one plain line — "
                                 f"repost it ({p['id']})"])
        self.assertEqual(decisions(self.settings, p["id"]), [])
        out = comments(("RobinLee", "APPROVE: fine *really*", "2026-10-14T09:00:00Z"),
                       ("RobinLee", "  REJECT: no\nsecond line", "2026-10-14T09:01:00Z"), pid=p["id"])
        lines, _ = adapters.record_decisions(self.github_settings(), NOW, runner=FakeRunner([(0, out, "")]))
        self.assertEqual(lines, [f"kaizen decisions: 2 comments look like a decision but aren't one plain line — "
                                 f"repost them ({p['id']})"])

    def test_a_valid_repost_quiets_the_near_miss_note(self):
        p = {**self.proposal(), "ref": "12", "adapter": "github"}
        proposals.save(p, self.settings)
        out = comments(("RobinLee", "APPROVE: fine *really*", "2026-10-14T09:00:00Z"),
                       ("RobinLee", "APPROVE: fine really", "2026-10-14T09:05:00Z"), pid=p["id"])
        lines, errors = adapters.record_decisions(self.github_settings(), NOW, runner=FakeRunner([(0, out, "")]))
        self.assertEqual(errors, [])
        self.assertEqual(lines, [f"{p['id']} approved by RobinLee: fine really"])
        acts = [action("APPROVE: fine", "robin", "2026-10-14T09:05:00.000Z"),
                action("APPROVE: fine *really*", "robin", "2026-10-14T09:00:00.000Z")]  # Trello lists newest first
        t = {**p, "id": p["id"][:-6] + "abcdef", "ref": CARD, "adapter": "trello"}
        proposals.save(t, self.settings)
        op = FakeOpener([card(t), (200, json.dumps(acts).encode())])
        both = {**self.github_settings(), "trello": self.trello_settings()["trello"],
                "approvers": ["robinlee", "robin"]}
        lines, errors = adapters.record_decisions(both, NOW, opener=op, env=ENV, runner=FakeRunner([(0, out, "")]))
        self.assertEqual(errors, [])
        self.assertEqual(lines, [f"{t['id']} approved by robin: fine"])
        out = comments(("RobinLee", "APPROVE: fine really", "2026-10-14T09:00:00Z"),
                       ("RobinLee", "REJECT: no *wait*", "2026-10-14T09:05:00Z"), pid=p["id"])  # a later near miss
        lines, _ = adapters.record_decisions(both, NOW, runner=FakeRunner([(0, out, "")]),
                                             opener=FakeOpener([card(t), (200, json.dumps(acts).encode())]), env=ENV)
        self.assertEqual(lines, [f"kaizen decisions: 1 comment looks like a decision but isn't one plain line — "
                                 f"repost it ({p['id']})"])

    def test_trello_near_misses_from_approvers_get_the_same_note(self):
        p = {**self.proposal(), "ref": CARD, "adapter": "trello"}
        proposals.save(p, self.settings)
        acts = [action("APPROVE: fine *really*", "robin", "2026-10-14T09:00:00.000Z"),
                action("REJECT: `no`", "mallory", "2026-10-14T09:01:00.000Z", member="3c" * 12)]
        op = FakeOpener([card(p), (200, json.dumps(acts).encode())])
        lines, errors = adapters.record_decisions(self.trello_settings(), NOW, opener=op, env=ENV)
        self.assertEqual(errors, [])
        self.assertEqual(lines, [f"kaizen decisions: 1 comment looks like a decision but isn't one plain line — "
                                 f"repost it ({p['id']})"])
        self.assertEqual(decisions(self.settings, p["id"]), [])

    def test_one_instruction_text_states_the_full_rule_everywhere(self):
        rule = adapters.INSTRUCTION
        for must in ("one plain line", "own comment", "300 characters", ":shortcode:", "No formatting",
                     "APPROVE: <your name>: <reason>", "at least one letter or digit", "’ ‘ “ ” – — …"):
            self.assertIn(must, rule)
        p = self.proposal()
        md = self.emit(p)
        self.assertEqual(md.count(rule), 1)
        self.assertEqual(md.count(adapters.PUNCT), 1)  # the allowlist is stated once, by INSTRUCTION
        run = FakeRunner([(0, "https://github.com/acme/rules/issues/12\n", "")])
        adapters.get(self.github_settings(), runner=run).emit_proposal(p)
        self.assertIn(rule, run.bodies[0])
        op = FakeOpener([(200, json.dumps({"id": CARD}).encode())])
        adapters.get(self.trello_settings(), opener=op, env=ENV).emit_proposal(p)
        desc = urllib.parse.parse_qs(op.requests[0].data.decode("utf-8"))["desc"][0]
        self.assertIn(rule, desc)

    def test_instruction_and_decide_texts_say_what_the_engine_does(self):
        rule = adapters.INSTRUCTION
        self.assertNotIn("  ", rule)
        self.assertNotIn("code, quotes or links", rule)  # quote marks are allowed; a block quote isn't
        self.assertIn("block quotes", rule)
        gh = adapters.github._decide(["robinlee"])
        self.assertEqual(gh, adapters.trello._decide(["robinlee"]))  # one shared text
        text = " ".join(gh)
        self.assertNotIn("names any comment", text)  # it says which proposal, not which comment
        self.assertIn("names the proposal", text)

    def test_file_adapter_reads_below_the_last_marker(self):  # a diff quoting the marker stays decidable
        p = self.proposal()
        p["diff"] = p["diff"] + "+# " + adapters.file.MARKER + "\n"
        clean = self.emit(p)
        self.assertEqual(clean.count(adapters.file.MARKER), 2)
        self.md(p).write_text(clean + "APPROVE: Robin: fine\n", encoding="utf-8")
        lines, errors = adapters.record_decisions(self.settings, NOW)
        self.assertEqual((lines, errors), ([f"{p['id']} approved by Robin: fine"], []))
        again = self.emit(p)  # a re-emit keeps the lines below the last marker only
        self.assertTrue(again.endswith(adapters.file.MARKER + "\n" + "APPROVE: Robin: fine\n"), again[-200:])
        for mod in (adapters.file, adapters.github, adapters.trello):  # the rule's text lives in INSTRUCTION only
            src = inspect.getsource(mod)
            for phrase in ("300 characters", "letters, digits", "no formatting", "shortcode"):
                self.assertNotIn(phrase, src.lower(), f"{mod.__name__} restates the rule: {phrase!r}")


if __name__ == "__main__":
    import unittest
    unittest.main()
