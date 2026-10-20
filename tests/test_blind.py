"""The blind reader test. Unlabelled human-vs-plainspoken pairs (normalised, length-matched, A/B
seeded), a form for human raters, panel prompts in both orders, and scoring with Wilson intervals, position bias
and agreement. Plus `kaizen mine` refusing a briefs folder that holds `.heldout`."""
import contextlib
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken import blind
from plainspoken import blind_score as bs
from plainspoken.adapters import llm_panel as lp

REPO = Path(__file__).resolve().parents[1]
MINING = REPO / "tests" / "fixtures" / "kaizen" / "mining"

OPUS = lp.PanelModel("claude-opus", "Anthropic", "claude-cli", "claude-opus-5-5", 0.0, 0.0)
GROK = lp.PanelModel("grok", "xAI", "openrouter", "x-ai/grok-test", 2.0, 10.0)
KIMI = lp.PanelModel("kimi", "Moonshot", "openrouter", "moonshotai/kimi-test", 1.0, 1.0)
SONNET = lp.PanelModel("sonnet", "Anthropic", "openrouter", "anthropic/claude-sonnet-test", 1.0, 1.0)
DEEPSEEK = lp.PanelModel("deepseek", "DeepSeek", "openrouter", "deepseek/deepseek-test", 1.0, 1.0)
MODEL_ID = "claude-opus-5-5-gen"

PANEL = """max_out_tokens = 800

[gateway]
transport = "openrouter"
base_url = "https://openrouter.test/api/v1"
key_env = "OPENROUTER_API_KEY"

[[model]]
name = "claude-opus"
vendor = "Anthropic"
transport = "claude-cli"
model = "claude-opus-5-5"
price_in = 0
price_out = 0

[[model]]
name = "grok"
vendor = "xAI"
model = "x-ai/grok-test"
price_in = 2.0
price_out = 10.0
"""

WORDS = ("garden river window kettle orchard ladder market harbour lantern pebble meadow saddle copper "
         "thistle cabin anchor biscuit ferry quarry willow").split()


def prose(seed: int, sentences: int, per: int = 10) -> str:
    """Plain sentences of `per` words from a small vocabulary: no markup, no authorship words."""
    out = []
    for s in range(sentences):
        words = [WORDS[(seed * 7 + s * 3 + i) % len(WORDS)] for i in range(per)]
        out.append(" ".join(words).capitalize() + ".")
    paras = [" ".join(out[i:i + 4]) for i in range(0, len(out), 4)]
    return "\n\n".join(paras) + "\n"


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def spec(self, n: int, *, human_sentences: int = 40, gen_sentences: int = 40) -> list[dict]:
        items = []
        for i in range(n):
            h = self.d / "src" / f"human-{i}.md"
            g = self.d / "src" / f"gen-{i}.md"
            h.parent.mkdir(parents=True, exist_ok=True)
            h.write_text(prose(2 * i, human_sentences), encoding="utf-8")
            g.write_text(prose(2 * i + 1, gen_sentences), encoding="utf-8")  # never the same text as h
            items.append({"id": f"case-{i}", "human": str(h), "generated": str(g), "model": MODEL_ID})
        return items

    def built(self, n: int = 4, seed: int = 7) -> Path:
        out = self.d / "blind"
        blind.build(self.spec(n), out, words=60, seed=seed)
        return out


class Normalise(unittest.TestCase):
    def test_normalise_strips_markup(self):
        md = ("---\ntitle: A post\ndraft: true\n---\n\n# The heading {#top}\n\n"
              "Intro with a [link to docs](https://example.com/docs) and **bold** and *italic* and `code`.\n\n"
              "<!-- module:start-here -->\n- [Jump to costs](#costs)\n"
              "- first item here\n- second item here\n1. numbered item\n"
              "<!-- /module:start-here -->\n\n"
              "> **Try this:** open the [tool](https://tool.example). It helps.\n\n"
              "| col one | col two |\n|---|---|\n| cell a | cell b |\n\n"
              "![alt words](/img/x.png)\n\n"
              "```python\nprint('hidden')\n```\n\n"
              "<div class=\"note\">Kept words</div>\n\n"
              "Closing line with ‘curly’ and “double” quotes.\n")
        text = blind.normalise(md)
        for gone in ("title:", "draft", "#", "{#top}", "https://", "**", "`", "module", "<!--", "Try this", "tool",
                     "|", "col one", "cell a", "Jump", "alt words", "img", "print", "hidden", "<div", "</div>", "*",
                     "‘", "’", "“", "”", "---"):
            self.assertNotIn(gone, text, gone)
        for kept in ("Intro with a link to docs and bold and italic and code.",
                     "first item here", "second item here", "numbered item", "Kept words",
                     "Closing line with 'curly' and \"double\" quotes."):
            self.assertIn(kept, text, kept)

    def test_normalise_inline_code_kept_verbatim(self):
        self.assertEqual(blind.normalise("See `out/*.png` and `a_b_c` *here*."), "See out/*.png and a_b_c here.")

    def test_normalise_paragraphs_and_lists(self):
        text = blind.normalise("One line\nwrapped here.\n\n\n\nTwo.\n- a item\n- b item\n")
        self.assertEqual(text, "One line wrapped here.\n\nTwo.\n\na item\n\nb item")

    def test_normalise_year_at_a_line_start_is_prose(self):
        """As in CommonMark, an ordered marker other than 1 can't interrupt a paragraph: a wrapped "1999." stays
        prose. A list still reads as a list, and "1." may start one mid-paragraph."""
        self.assertEqual(blind.normalise("It all began in\n1999. Then we moved.\n"),
                         "It all began in 1999. Then we moved.")
        self.assertEqual(blind.normalise("Steps:\n1. first one\n2. second one\n   wrapped on\n3. third one\n"),
                         "Steps:\n\nfirst one\n\nsecond one\n\nwrapped on\n\nthird one")
        self.assertEqual(blind.normalise("1999. That was the year.\n"), "That was the year.")  # a list, as CommonMark

    def test_normalise_setext_and_rules(self):
        text = blind.normalise("Title\n=====\n\nBody one.\n\n---\n\nSub\n---\n\nBody two.\n")
        self.assertEqual(text, "Body one.\n\nBody two.")


class Excerpt(unittest.TestCase):
    def test_excerpt_whole_sentences_shortest_run(self):
        text = "One two three. Four five six seven.\n\nEight nine. Ten eleven twelve."
        self.assertEqual(blind.excerpt(text, 3), "One two three.")
        self.assertEqual(blind.excerpt(text, 4), "One two three. Four five six seven.")
        self.assertEqual(blind.excerpt(text, 8), "One two three. Four five six seven.\n\nEight nine.")
        self.assertEqual(blind.excerpt(text, 500), text)  # shorter than asked: the whole text

    def test_excerpt_needs_positive_words(self):
        with self.assertRaises(ValueError):
            blind.excerpt("Some text.", 0)


class Build(Tmp):
    def test_length_matched(self):
        out = self.built(6)
        for line in (out / "pairs.jsonl").read_text(encoding="utf-8").splitlines():
            p = json.loads(line)
            wa, wb = len(p["a"].split()), len(p["b"].split())
            self.assertLessEqual(abs(wa - wb), 0.15 * max(wa, wb), p["pair"])
            self.assertGreaterEqual(min(wa, wb), 60)

    def test_length_mismatch_refused_naming_the_item(self):
        spec = self.spec(3)
        short = self.d / "src" / "short.md"
        short.write_text(prose(9, 4), encoding="utf-8")  # 40 words against 60+
        spec[1]["generated"] = str(short)
        out = self.d / "blind"
        with self.assertRaises(blind.BlindRefusal) as cm:
            blind.build(spec, out, words=60, seed=1)
        self.assertIn("case-1", str(cm.exception))
        self.assertNotIn("case-0", str(cm.exception))
        self.assertFalse(out.exists())  # nothing written

    def test_spelling_markers(self):
        gb = blind.spelling("The colour of the centre was organised, and we travelled on. Their behaviour, too.")
        self.assertEqual((gb["au_gb"], gb["us"], gb["locale"]), (5, 0, "au/gb"))
        us = blind.spelling("The color of the center was organized, and we traveled on.")
        self.assertEqual((us["au_gb"], us["us"], us["locale"]), (0, 4, "us"))
        self.assertEqual(blind.spelling("Plain words with no marker at all. A prize, a size, a promise.")["locale"],
                         "unknown")
        self.assertEqual(blind.spelling("The colour and the color.")["locale"], "mixed")
        # look-alikes that aren't locale markers in Australian English
        self.assertEqual(blind.spelling("The Labor Party's honorary members were humorous.")["locale"], "unknown")

    def test_gray_and_grey_markers_skip_names(self):
        """The gray/grey marker is lowercase only and never right after a capitalised first name, so the surname
        Gray (or Earl Grey) isn't a spelling choice."""
        for text, au_gb, us in (("Asa Gray wrote the field guide.", 0, 0), ("A paper by Gray and Lee.", 0, 0),
                                ("Gray skies all week.", 0, 0), ("the gray cat sat", 0, 1),
                                ("The gray cat sat. The grey dog too.", 1, 1), ("Ask Jim gray about it.", 0, 0),
                                ("A cup of Earl Grey, please.", 0, 0), ("a grey day, and grays", 1, 1)):
            got = blind.spelling(text)
            self.assertEqual((got["au_gb"], got["us"]), (au_gb, us), text)

    def with_marker(self, path: Path, word: str) -> None:
        text = path.read_text(encoding="utf-8")
        path.write_text(f"The {word} was plain. " + text, encoding="utf-8")

    def test_spelling_locale_mismatch_refused(self):
        spec = self.spec(3)
        self.with_marker(Path(spec[1]["human"]), "colour")
        self.with_marker(Path(spec[1]["generated"]), "color")
        self.with_marker(Path(spec[2]["human"]), "colour")  # a marker on one side only: allowed
        out = self.d / "blind"
        with self.assertRaises(blind.BlindRefusal) as cm:
            blind.build(spec, out, words=60, seed=1)
        self.assertIn("case-1", str(cm.exception))
        self.assertIn("spell", str(cm.exception))
        self.assertEqual(cm.exception.ids, ["case-1"])
        self.assertFalse(out.exists())  # nothing written

    def test_spelling_recorded_and_same_locale_allowed(self):
        spec = self.spec(2)
        self.with_marker(Path(spec[0]["human"]), "colour")
        self.with_marker(Path(spec[0]["generated"]), "centre")
        out = self.d / "blind"
        blind.build(spec, out, words=60, seed=1)
        meta = json.loads((out / "build.json").read_text(encoding="utf-8"))
        first = meta["sources"][0]
        self.assertEqual(first["human"]["spelling"], {"au_gb": 1, "us": 0, "locale": "au/gb"})
        self.assertEqual(first["generated"]["spelling"]["locale"], "au/gb")
        self.assertEqual(meta["sources"][1]["human"]["spelling"]["locale"], "unknown")

    def test_build_no_labels_in_pairs(self):
        out = self.built(4)
        raw = (out / "pairs.jsonl").read_text(encoding="utf-8")
        for leak in ("human", "generated", "model", MODEL_ID, "case-", str(self.d), "src", ".md"):
            self.assertNotIn(leak, raw, leak)
        for line in raw.splitlines():
            self.assertEqual(set(json.loads(line)), {"pair", "a", "b"})
        key = json.loads((out / "key.json").read_text(encoding="utf-8"))
        self.assertEqual(len(key), 4)
        for pair, k in key.items():
            self.assertIn(k["human"], ("a", "b"))
            self.assertEqual(k["model"], MODEL_ID)
        self.assertTrue((out / ".heldout").is_file())
        meta = json.loads((out / "build.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["seed"], meta["words"]), (7, 60))
        self.assertEqual(len(meta["sources"]), 4)
        self.assertEqual(len(meta["sources"][0]["human"]["sha256"]), 64)

    def test_build_seeded(self):
        spec = self.spec(20)

        def assignment(seed: int, name: str) -> list[str]:
            out = self.d / name
            blind.build(spec, out, words=60, seed=seed)
            key = json.loads((out / "key.json").read_text(encoding="utf-8"))
            return [key[p]["human"] for p in sorted(key)]

        first, again, other = assignment(11, "a"), assignment(11, "b"), assignment(12, "c")
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)
        self.assertEqual(first.count("a"), 10)  # balanced: half the people's texts sit in position A

    def test_build_refuses_an_existing_build(self):
        out = self.built(2)
        with self.assertRaises(blind.BlindError):
            blind.build(self.spec(2), out, words=60, seed=1)

    def test_partial_build_leaves_nothing(self):
        """A write that fails part-way removes what the build wrote (and the folder it made), so a re-run isn't
        refused as 'already holds a build'."""
        real = blind._write

        def failing(path, text):
            if path.name == blind.PAIRS:
                raise OSError(28, "No space left on device")
            real(path, text)
        for existed in (False, True):
            out = self.d / f"blind-{existed}"
            if existed:
                out.mkdir()
                (out / "notes.txt").write_text("mine\n", encoding="utf-8")
            with mock.patch.object(blind, "_write", failing), self.assertRaises(OSError):
                blind.build(self.spec(2), out, words=60, seed=1)
            self.assertEqual(sorted(p.name for p in out.iterdir()) if out.exists() else None,
                             ["notes.txt"] if existed else None)
            blind.build(self.spec(2), out, words=60, seed=1)
            self.assertTrue((out / blind.PAIRS).is_file())

    def test_build_bad_spec(self):
        for bad in ([{"id": "x", "human": "nope.md", "generated": "nope.md", "model": "m"}],
                    [{"id": "x", "human": "a", "model": "m"}],
                    [{"id": "x", "human": "a", "generated": "b", "model": "m", "colour": "red"}],
                    []):
            with self.assertRaises(blind.BlindError, msg=bad):
                blind.build(bad, self.d / "never", words=60, seed=1)
        self.assertFalse((self.d / "never").exists())


class Form(Tmp):
    def test_form_and_answers(self):
        out = self.built(3)
        path = blind.form(out)
        text = path.read_text(encoding="utf-8")
        self.assertIn("written by a person", text)
        for leak in ("plainspoken", "AI", "model", "generated", MODEL_ID, "tell"):
            self.assertNotIn(leak, text, leak)
        pairs = [json.loads(x)["pair"] for x in (out / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
        for p in pairs:
            self.assertIn(p, text)
        rows = list(csv.reader((out / "answers.csv").open(encoding="utf-8")))
        self.assertEqual(rows[0], ["rater", "pair", "human", "better"])
        self.assertEqual([r[1] for r in rows[1:]], pairs)

    def test_form_keeps_filled_answers(self):
        out = self.built(2)
        blind.form(out)
        (out / "answers.csv").write_text("rater,pair,human,better\nann,p01,a,b\n", encoding="utf-8")
        blind.form(out)
        self.assertIn("ann", (out / "answers.csv").read_text(encoding="utf-8"))


class Prompts(Tmp):
    def test_both_orders(self):
        out = self.built(3)
        pairs = {p["pair"]: p for p in map(json.loads, (out / "pairs.jsonl").read_text(encoding="utf-8").splitlines())}
        got = blind.prompts(out)
        self.assertEqual(len(got), 2 * len(pairs))
        keys = [k for k, _ in got]
        self.assertEqual(keys, [f"{p}|{o}" for p in pairs for o in ("ab", "ba")])
        for key, prompt in got:
            pair, order = key.split("|")
            a, b = pairs[pair]["a"], pairs[pair]["b"]
            first, second = (a, b) if order == "ab" else (b, a)
            self.assertLess(prompt.index("Text A"), prompt.index(first))
            self.assertLess(prompt.index(first), prompt.index("Text B"))
            self.assertLess(prompt.index("Text B"), prompt.index(second))

    def test_prompt_names_no_rules_or_plugin(self):
        out = self.built(1)
        prompt = blind.prompts(out)[0][1]
        for word in ("plainspoken", "tell", "rule", "AI", "model", "em dash"):
            self.assertNotIn(word, prompt, word)
        self.assertIn("written by a person", prompt)


class ParseBlind(unittest.TestCase):
    def test_parse_blind_bare(self):
        self.assertEqual(blind.parse_blind('{"human": "A", "better": "B"}'), ({"human": "A", "better": "B"}, ""))

    def test_parse_blind_fenced(self):
        self.assertEqual(blind.parse_blind('```json\n{"human": "b", "better": "B"}\n```'),
                         ({"human": "B", "better": "B"}, ""))

    def test_parse_blind_invalid_letter(self):
        got, why = blind.parse_blind('{"human": "C", "better": "A"}')
        self.assertIsNone(got)
        self.assertIn("human", why)

    def test_parse_blind_refuses_extra_keys(self):
        got, why = blind.parse_blind('{"human": "A", "better": "B", "why": "the rhythm"}')
        self.assertIsNone(got)
        self.assertEqual(why, "unexpected key why")

    def test_parse_blind_errors(self):
        for reply in ('I think A. {"human": "A", "better": "A"}', '{"human": "A"}', '["A", "B"]', "",
                      '{"human": "both", "better": "A"}', '{"human": 1, "better": "A"}'):
            got, why = blind.parse_blind(reply)
            self.assertIsNone(got, reply)
            self.assertTrue(why, reply)


def mk_reply(pair: str, order: str, model: lp.PanelModel, human: str | None = None, better: str = "A", *,
             text: str | None = None, error: str | None = None) -> lp.Reply:
    body = text if text is not None else (json.dumps({"human": human, "better": better}) if human else "")
    return lp.Reply(key=f"{pair}|{order}|{model.name}", name=model.name, model_requested=model.model,
                    model_reported="" if error else model.model + "-0915", text=body, in_tokens=10, out_tokens=5,
                    cost_usd=0.0, billed=model.billed, at="2026-10-16T01:02:03Z", error=error)


def printed(order: str, text: str) -> str:
    """The letter shown for the pair's own text `text` ('a'/'b') in `order`."""
    return ("A" if text == "a" else "B") if order == "ab" else ("B" if text == "a" else "A")


class Score(Tmp):
    def setUp(self):
        super().setUp()
        self.out = self.built(10)
        self.key = json.loads((self.out / "key.json").read_text(encoding="utf-8"))

    def other(self, x: str) -> str:
        return "b" if x == "a" else "a"

    def detector(self, model, right=lambda pair, order: True, prefers_human=True) -> list[lp.Reply]:
        out = []
        for pair, k in self.key.items():
            for order in ("ab", "ba"):
                pick = k["human"] if right(pair, order) else self.other(k["human"])
                better = k["human"] if prefers_human else self.other(k["human"])
                out.append(mk_reply(pair, order, model, printed(order, pick), printed(order, better)))
        return out

    def judge(self, s: dict, name: str) -> dict:
        return next(j for j in s["judges"] if j["name"] == name)

    def test_score_perfect_detector(self):
        s = bs.score(self.out, self.detector(OPUS), None)
        j = self.judge(s, "claude-opus")
        self.assertEqual(j["tier"], "tier-2 proxy")
        self.assertEqual(j["n"], 20)
        self.assertEqual(j["found_human"]["value"], 1.0)
        self.assertEqual(j["plainspoken_judged_human"]["value"], 0.0)
        lo, hi = j["found_human"]["ci"]
        self.assertEqual(j["plainspoken_judged_human"]["ci"], [1 - hi, 1 - lo])
        self.assertEqual(j["prefers_plainspoken"]["value"], 0.0)
        self.assertEqual(j["errors"], 0)
        self.assertIn("claude-opus-5-5-0915", j["model_reported"])

    def test_score_coin_flip_ci_spans_half(self):
        pairs = sorted(self.key)
        s = bs.score(self.out, self.detector(OPUS, right=lambda p, o: pairs.index(p) % 2 == 0), None)
        j = self.judge(s, "claude-opus")
        self.assertEqual(j["found_human"]["value"], 0.5)
        lo, hi = j["plainspoken_judged_human"]["ci"]
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_score_position_bias(self):
        replies = [mk_reply(p, o, OPUS, "A", "A") for p in self.key for o in ("ab", "ba")]
        s = bs.score(self.out, replies, None)
        j = self.judge(s, "claude-opus")
        self.assertEqual(j["position_a"]["value"], 1.0)
        self.assertEqual(j["found_human"]["value"], 0.5)  # always-A finds the person in exactly one order
        self.assertEqual(j["orders_agree"], {"k": 0, "n": 10})

    def test_score_order_disagreement_counts_each(self):
        # ab right, ba wrong: each order is its own judgement
        s = bs.score(self.out, self.detector(OPUS, right=lambda p, o: o == "ab"), None)
        j = self.judge(s, "claude-opus")
        self.assertEqual((j["found_human"]["k"], j["n"]), (10, 20))
        self.assertEqual(j["orders_agree"], {"k": 0, "n": 10})

    def test_score_errors_counted(self):
        replies = self.detector(OPUS)
        replies[0] = mk_reply(replies[0].key.split("|")[0], replies[0].key.split("|")[1], OPUS, text="maybe A?")
        replies[1] = mk_reply(replies[1].key.split("|")[0], replies[1].key.split("|")[1], OPUS, error="HTTP 500")
        s = bs.score(self.out, replies, None)
        j = self.judge(s, "claude-opus")
        self.assertEqual((j["n"], j["errors"]), (18, 2))
        self.assertEqual(j["found_human"]["value"], 1.0)
        self.assertEqual(sum(j["error_reasons"].values()), 2)

    def test_score_missing_kept_apart_from_errors(self):
        """A pair and order with no reply is missing, on a judge's row and on the majority, never an error."""
        gone = {("p01", "ab"), ("p02", "ba"), ("p03", "ab")}

        def without(replies, items):
            return [r for r in replies if tuple(r.key.split("|")[:2]) not in items]
        replies = (without(self.detector(OPUS), gone) + without(self.detector(GROK), {("p01", "ab")})
                   + without(self.detector(KIMI), {("p01", "ab")}))
        s = bs.score(self.out, replies, None)
        opus = self.judge(s, "claude-opus")
        self.assertEqual((opus["n"], opus["errors"], opus["missing"]), (17, 0, 3))
        self.assertEqual((self.judge(s, "grok")["missing"], self.judge(s, "grok")["n"]), (1, 19))
        maj = next(m for m in s["majority"] if m["name"] == "panel majority")
        self.assertEqual((maj["n"], maj["errors"], maj["missing"]), (19, 0, 1))
        self.assertIn("| missing |", bs.render(s))
        path = self.d / "answers.csv"
        path.write_text("rater,pair,human,better\nann,p01,a,a\nann,p02,b,b\n", encoding="utf-8")
        ann = self.judge(bs.score(self.out, None, path), "ann")
        self.assertEqual((ann["n"], ann["errors"], ann["missing"]), (2, 0, 8))

    def test_score_names_off_key_replies(self):
        replies = self.detector(OPUS) + [mk_reply("p99", "ab", OPUS, "A"), mk_reply("p01", "xy", OPUS, "A"),
                                         lp.Reply(**{**mk_reply("p01", "ab", OPUS, "A").__dict__, "key": "junk"})]
        s = bs.score(self.out, replies, None)
        self.assertEqual(self.judge(s, "claude-opus")["n"], 20)
        (w,) = [w for w in s["warnings"] if "isn't a pair" in w]
        self.assertIn("3 replies", w)
        self.assertIn("p99|ab|claude-opus", w)
        self.assertIn(w, bs.render(s))

    def test_score_anthropic_from_the_model_served(self):
        """An alias (opus, sonnet, haiku) or a claude-* id that answered is Anthropic, whatever was asked for."""
        alias = lp.PanelModel("opus-alias", "", "claude-cli", "opus", 0.0, 0.0)
        relay = lp.PanelModel("relay", "", "openrouter", "some-router/auto", 1.0, 1.0)
        served = [(alias, "claude-opus-5-5"), (relay, "claude-haiku-5"), (GROK, "x-ai/grok-test"),
                  (KIMI, "moonshotai/kimi-test")]
        replies = [lp.Reply(**{**r.__dict__, "model_reported": answered}) for m, answered in served
                   for r in self.detector(m)]
        s = bs.score(self.out, replies, None)
        self.assertTrue(self.judge(s, "opus-alias")["anthropic"])
        self.assertTrue(self.judge(s, "relay")["anthropic"])
        na = next(m for m in s["majority"] if m["name"] == "non-Anthropic majority")
        self.assertEqual(na["judges"], ["grok", "kimi"])
        failed = [mk_reply(p, o, alias, error="claude-cli: timed out") for p in self.key for o in ("ab", "ba")]
        self.assertTrue(self.judge(bs.score(self.out, failed, None), "opus-alias")["anthropic"])  # nothing served

    def test_score_majority_and_kappa(self):
        replies = self.detector(OPUS) + self.detector(GROK) + self.detector(KIMI, right=lambda p, o: False)
        s = bs.score(self.out, replies, None)
        maj = next(m for m in s["majority"] if m["tier"] == "tier-2 proxy")
        self.assertEqual(maj["found_human"]["value"], 1.0)
        self.assertEqual(maj["n"], 20)
        k = s["kappa"]["tier-2 proxy"]
        self.assertEqual((k["judges"], k["items"]), (3, 20))
        self.assertIsNotNone(k["value"])

    def test_score_non_anthropic_majority(self):
        # the Anthropic models miss the person, the others mostly find them: tier 2 is the non-Anthropic majority
        wrong = lambda p, o: False  # noqa: E731
        replies = (self.detector(OPUS, right=wrong) + self.detector(SONNET, right=wrong) + self.detector(GROK)
                   + self.detector(KIMI) + self.detector(DEEPSEEK, right=wrong))
        s = bs.score(self.out, replies, None)
        rows = {m["name"]: m for m in s["majority"] if m["tier"] == "tier-2 proxy"}
        self.assertEqual(rows["panel majority"]["found_human"]["value"], 0.0)
        na = rows["non-Anthropic majority"]
        self.assertEqual(na["judges"], ["grok", "kimi", "deepseek"])
        self.assertEqual(na["found_human"]["value"], 1.0)
        self.assertEqual(rows["panel majority"]["judges"], ["claude-opus", "sonnet", "grok", "kimi", "deepseek"])
        self.assertEqual(s["warnings"], [])
        self.assertTrue(self.judge(s, "claude-opus")["anthropic"])
        self.assertFalse(self.judge(s, "grok")["anthropic"])

    def test_score_all_anthropic_tier2_warns(self):
        s = bs.score(self.out, self.detector(OPUS) + self.detector(SONNET), None)
        self.assertNotIn("non-Anthropic majority", [m["name"] for m in s["majority"]])
        self.assertEqual(len(s["warnings"]), 1)
        self.assertIn("Anthropic", s["warnings"][0])
        self.assertIn("warning:", bs.render(s))

    def test_score_human_csv_tier1(self):
        path = self.d / "answers.csv"
        rows = ["rater,pair,human,better"]
        for pair, k in self.key.items():
            rows.append(f"ann,{pair},{k['human']},{k['human']}")  # finds the person, prefers them
            rows.append(f"bob,{pair},{self.other(k['human'])},{self.other(k['human'])}")
        rows.append(",p01,,")  # an unfilled template row is skipped
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        s = bs.score(self.out, None, path)
        ann, bob = self.judge(s, "ann"), self.judge(s, "bob")
        self.assertEqual((ann["tier"], ann["n"]), ("tier-1", 10))
        self.assertEqual(ann["found_human"]["value"], 1.0)
        self.assertEqual(bob["plainspoken_judged_human"]["value"], 1.0)
        self.assertEqual(bob["prefers_plainspoken"]["value"], 1.0)
        self.assertEqual(s["kappa"]["tier-1"]["judges"], 2)

    def test_score_human_csv_bad_input(self):
        for body in ("rater,pair\nann,p01\n", "rater,pair,human,better\nann,p99,a,a\n",
                     "rater,pair,human,better\nann,p01,a,a\nann,p01,b,b\n", "rater,pair,human,better\n,p01,a,a\n"):
            path = self.d / "bad.csv"
            path.write_text(body, encoding="utf-8")
            with self.assertRaises(blind.BlindError, msg=body):
                bs.score(self.out, None, path)

    def test_score_human_csv_blank_answer_is_an_error(self):
        path = self.d / "answers.csv"
        path.write_text("rater,pair,human,better\nann,p01,a,\nann,p02,c,a\n", encoding="utf-8")
        s = bs.score(self.out, None, path)
        ann = self.judge(s, "ann")
        self.assertEqual((ann["n"], ann["errors"]), (0, 2))

    def test_sampling_recorded_per_transport(self):
        s = bs.score(self.out, self.detector(OPUS) + self.detector(GROK), None)
        self.assertEqual(s["sampling"], {"openrouter": lp.SAMPLING["openrouter"],
                                         "claude-cli": lp.SAMPLING["claude-cli"]})
        md = bs.render(s)
        self.assertIn("- Sampling: openrouter at temperature 0 · claude-cli at", md)
        self.assertIn("isn't comparable across transports", md)
        self.assertEqual(bs.score(self.out, self.detector(GROK), None)["sampling"],
                         {"openrouter": lp.SAMPLING["openrouter"]})
        path = self.d / "answers.csv"
        path.write_text("rater,pair,human,better\nann,p01,a,a\n", encoding="utf-8")
        people = bs.score(self.out, None, path)
        self.assertEqual(people["sampling"], {})
        self.assertNotIn("Sampling", bs.render(people))

    def test_render_reports_ci_tier_and_no_composite(self):
        s = bs.score(self.out, self.detector(OPUS), None)
        md = bs.render(s)
        self.assertIn("tier-2 proxy", md)
        self.assertIn("claude-opus-5-5-0915", md)
        self.assertIn("[", md)
        self.assertNotIn("composite", md.lower().replace("no combined score", ""))


class FakeCall:
    """Stands in for llm_panel.call: a perfect detector that reads the build's key."""

    def __init__(self, out: Path):
        self.key = json.loads((out / "key.json").read_text(encoding="utf-8"))
        self.keys: list[str] = []

    def __call__(self, model, prompt, panel, *, opener=None, runner=None, env=None, key=""):
        self.keys.append(key)
        pair, order, _ = key.split("|")
        h = self.key[pair]["human"]
        text = json.dumps({"human": printed(order, h), "better": printed(order, h)})
        return lp.Reply(key=key, name=model.name, model_requested=model.model, model_reported=model.model + "-x",
                        text=text, in_tokens=100, out_tokens=5, cost_usd=0.001 if model.billed else 0.02,
                        billed=model.billed, at="2026-10-16T01:02:03Z", error=None)


class Cli(Tmp):
    def setUp(self):
        super().setUp()
        old = os.getcwd()  # `blind score` appends to the project's eval history: keep it in the temp folder
        os.chdir(self.d)
        self.addCleanup(os.chdir, old)
        env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""})
        env.start()
        self.addCleanup(env.stop)
        self.panel = self.d / "panel.toml"
        self.panel.write_text(PANEL, encoding="utf-8")

    def write_spec(self, n: int = 3) -> Path:
        spec = self.spec(n)
        for item in spec:  # relative to the spec file
            item["human"] = str(Path(item["human"]).relative_to(self.d))
            item["generated"] = str(Path(item["generated"]).relative_to(self.d))
        path = self.d / "spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def test_cli_build_form_run_score(self):
        out = self.d / "blind"
        code, so, err = run_cli("eval", "blind", "build", "--spec", str(self.write_spec()), "--out", str(out),
                                "--words", "60", "--seed", "3")
        self.assertEqual(code, 0, err)
        self.assertTrue((out / "pairs.jsonl").is_file())
        code, so, err = run_cli("eval", "blind", "form", "--out", str(out))
        self.assertEqual(code, 0, err)
        self.assertTrue((out / "form.md").is_file())
        fake = FakeCall(out)
        with mock.patch.object(lp, "call", fake):
            code, so, err = run_cli("eval", "blind", "run", "--out", str(out), "--panel", str(self.panel),
                                    "--models", "claude-opus", "--dry-run")
            self.assertEqual(code, 0, err)
            self.assertEqual(fake.keys, [])
            self.assertFalse((out / "replies.jsonl").exists())
            code, so, err = run_cli("eval", "blind", "run", "--out", str(out), "--panel", str(self.panel),
                                    "--models", "claude-opus")
            self.assertEqual(code, 0, err)
            self.assertEqual(len(fake.keys), 6)
            self.assertTrue(all(k.endswith("|claude-opus") for k in fake.keys))
            run_cli("eval", "blind", "run", "--out", str(out), "--panel", str(self.panel), "--models", "claude-opus")
            self.assertEqual(len(fake.keys), 6)  # resumed: nothing called twice
            code, so, err = run_cli("eval", "blind", "run", "--out", str(out), "--panel", str(self.panel),
                                    "--models", "claude-opus,grok")
            self.assertEqual(code, 1)  # grok is billed: needs --yes
            self.assertIn("--yes", err)
        answers = self.d / "answers.csv"
        key = json.loads((out / "key.json").read_text(encoding="utf-8"))
        answers.write_text("rater,pair,human,better\n" + "".join(f"ann,{p},{k['human']},a\n" for p, k in key.items()),
                           encoding="utf-8")
        code, so, err = run_cli("eval", "blind", "score", "--out", str(out), "--answers", str(answers))
        self.assertEqual(code, 0, err)
        summary = json.loads((out / "score.json").read_text(encoding="utf-8"))
        names = {j["name"]: j for j in summary["judges"]}
        self.assertEqual(names["claude-opus"]["found_human"]["value"], 1.0)
        self.assertEqual(names["ann"]["tier"], "tier-1")
        self.assertIn("tier-1", (out / "score.md").read_text(encoding="utf-8"))
        self.assertIn("tier-2 proxy", so)
        self.assertIn("warning: every tier-2 judge is an Anthropic model", so)
        from plainspoken import evalhistory as eh
        self.assertEqual([r["tier"] for r in eh.read(self.d)], ["tier-1"])  # no tier-2 line from Claude alone

    def test_cli_run_exits_1_when_a_call_failed(self):
        out = self.d / "blind"
        code, _, err = run_cli("eval", "blind", "build", "--spec", str(self.write_spec(2)), "--out", str(out),
                               "--words", "60", "--seed", "3")
        self.assertEqual(code, 0, err)
        fake = FakeCall(out)

        def flaky(model, prompt, panel, **kw):
            r = fake(model, prompt, panel, **kw)
            if kw.get("key", "").startswith("p01|ab"):
                return lp.Reply(**{**r.__dict__, "text": "", "error": "claude-cli: timed out"})
            return r
        with mock.patch.object(lp, "call", flaky):
            code, so, err = run_cli("eval", "blind", "run", "--out", str(out), "--panel", str(self.panel),
                                    "--models", "claude-opus")
        self.assertEqual(code, 1)
        self.assertIn("1 failed", so)
        self.assertIn("plainspoken: eval blind run:", err)
        with mock.patch.object(lp, "call", fake):  # the retry succeeds: exit 0
            code, so, err = run_cli("eval", "blind", "run", "--out", str(out), "--panel", str(self.panel),
                                    "--models", "claude-opus")
        self.assertEqual(code, 0, err)

    def test_cli_build_refusal_exit_1(self):
        spec = self.write_spec(2)
        items = json.loads(spec.read_text(encoding="utf-8"))
        (self.d / "src" / "short.md").write_text(prose(5, 3), encoding="utf-8")
        items[0]["human"] = "src/short.md"
        spec.write_text(json.dumps(items), encoding="utf-8")
        out = self.d / "blind"
        code, _, err = run_cli("eval", "blind", "build", "--spec", str(spec), "--out", str(out), "--words", "60",
                               "--seed", "1")
        self.assertEqual(code, 1)
        self.assertIn("case-0", err)
        self.assertTrue(err.startswith("plainspoken: eval blind build: "))
        self.assertFalse(out.exists())

    def test_cli_build_spelling_refusal_exit_1(self):
        spec = self.write_spec(2)
        for name, word in (("human-1.md", "colour"), ("gen-1.md", "color")):
            path = self.d / "src" / name
            path.write_text(f"The {word} was plain. " + path.read_text(encoding="utf-8"), encoding="utf-8")
        out = self.d / "blind"
        code, _, err = run_cli("eval", "blind", "build", "--spec", str(spec), "--out", str(out), "--words", "60",
                               "--seed", "1")
        self.assertEqual(code, 1)
        self.assertIn("case-1", err)
        self.assertIn("spelling", err)
        self.assertFalse(out.exists())

    def test_cli_build_needs_seed_and_good_spec(self):
        spec = self.write_spec(1)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                cli_main.main(["eval", "blind", "build", "--spec", str(spec), "--out", str(self.d / "o")])
        self.assertEqual(cm.exception.code, 2)
        (self.d / "bad.json").write_text("{not json", encoding="utf-8")
        code, _, err = run_cli("eval", "blind", "build", "--spec", str(self.d / "bad.json"), "--out",
                               str(self.d / "o"), "--seed", "1")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_cli_out_naming_a_file(self):
        afile = self.d / "afile"
        afile.write_text("x\n", encoding="utf-8")
        spec = self.write_spec(1)
        for argv in (("score", "--out", str(afile)), ("form", "--out", str(afile)),
                     ("run", "--out", str(afile), "--panel", str(self.panel), "--models", "claude-opus"),
                     ("build", "--spec", str(spec), "--out", str(afile), "--seed", "1")):
            code, _, err = run_cli("eval", "blind", *argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(f"{afile}: not a folder", err)
            self.assertNotIn("internal error", err)

    def test_cli_score_and_run_need_a_build(self):
        for argv in (("score", "--out", str(self.d / "none")),
                     ("run", "--out", str(self.d / "none"), "--panel", str(self.panel), "--models", "claude-opus"),
                     ("form", "--out", str(self.d / "none"))):
            code, _, err = run_cli("eval", "blind", *argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("eval blind", err)


class MiningHeldout(unittest.TestCase):
    def test_mining_refuses_heldout(self):
        tmp = Path(tempfile.mkdtemp(prefix="plainspoken-blind-test-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = tmp / "project"
        root.mkdir()
        (root / ".git").mkdir()
        shutil.copytree(MINING / "corpus", root / "corpus")
        shutil.copytree(MINING / "drafts", root / "drafts")
        shutil.copytree(MINING / "briefs", root / "briefs")
        (root / "briefs" / ".heldout").write_text("held out\n", encoding="utf-8")
        e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        e["PYTHONPATH"] = str(REPO / "lib")
        for extra in ((), ("--corpus", "corpus/*.md")):  # refused before the corpus is even looked at
            r = subprocess.run([sys.executable, "-m", "plainspoken", "kaizen", "mine", "--drafts", "drafts",
                                "--briefs", "briefs", "--dry-run", *extra], cwd=root, capture_output=True, text=True,
                               env=e)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertTrue(r.stderr.startswith("plainspoken: kaizen mine: "), r.stderr)
            self.assertIn(".heldout", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
        self.assertFalse((root / ".plainspoken").exists())


if __name__ == "__main__":
    unittest.main()
