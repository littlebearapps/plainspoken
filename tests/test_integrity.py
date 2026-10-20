"""lib/plainspoken/integrity.py: the no-ledger checks and the linear tag scanners shared with extraction."""
import random
import re
import time
import unittest

from plainspoken import extraction, integrity

FAST = 1.0  # seconds, in-process, for a 300 KB+ adversarial file

# The regexes the linear scanners replace: they must find exactly the same spans.
CHART_RE = re.compile(r"<figure[\s>].*?</figure>|<svg[\s>].*?</svg>", re.S | re.I)
VISIBLE_RE = re.compile(r"<(text|tspan|title|desc|figcaption)[^>]*>(.*?)</\1>", re.S | re.I)
JSONLD_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
TOKENS = ["<figure>", "<figure ", "</figure>", "<svg>", "<SVG\n", "</svg>", "</SVG>", "<text>", "<Text a='1'>",
          "</text>", "<tspan>", "</tspan>", "<title>", "</title>", "<desc>", "</desc>", "<figcaption>",
          "</figcaption>", "<textPath>", ">", "<", "1%", " ", "\n", "x", '<script type="application/ld+json">',
          "<script>", '<SCRIPT a=1 type="application/ld+json" b>', "</script>", "</SCRIPT>", "<figurex>", "<svg/>",
          "<script ", ' type="application/ld+json"']  # stacked openings with the type after them

ADVERSARIAL = {
    "unclosed figure": "<figure><svg><text>1%</text>\n" * 12000,
    "unclosed svg": "<svg><text>1%</text>\n" * 15000,
    "unclosed text in a chart": "<svg>" + "<text>1%\n" * 40000 + "</svg>",
    "unclosed tspan in a chart": "<svg>" + "<tspan>1%\n" * 35000 + "</svg>",
    "no > in a chart": "<svg>" + "<text 1%\n" * 40000 + "</svg>",
    "unclosed JSON-LD": '<script type="application/ld+json">{"a": "1%"}\n' * 7000,
    "stacked script openings": "<script " * 40000 + ">1%\n",  # was 82 s
    "unclosed aria-label": "<svg>" + 'aria-label="1% \n' * 20000 + "</svg>",
    "unclosed marker": "<figure><svg><text>1%</text></svg></figure>\n<!-- integrity:allow \n" * 6000,
}


class Scanners(unittest.TestCase):
    def test_same_spans_as_the_regexes(self):
        rng = random.Random(7)
        for _ in range(5000):
            s = "".join(rng.choice(TOKENS) for _ in range(rng.randint(0, 14)))
            self.assertEqual(integrity.chart_spans(s), [(m.start(), m.end()) for m in CHART_RE.finditer(s)], s)
            self.assertEqual(integrity.visible_parts(s), [(m.start(2), m.group(2)) for m in VISIBLE_RE.finditer(s)], s)
            self.assertEqual(extraction._jsonld_blocks(s),
                             [(m.start(), m.start(1), m.end()) for m in JSONLD_RE.finditer(s)], s)

    def test_adversarial_shapes_are_fast(self):
        for name, text in ADVERSARIAL.items():
            with self.subTest(name):
                self.assertGreater(len(text.encode("utf-8")), 300_000)
                start = time.monotonic()
                integrity.findings(text)
                self.assertLess(time.monotonic() - start, FAST)
                start = time.monotonic()
                extraction.value_gaps(text, {"claims": []})
                self.assertLess(time.monotonic() - start, FAST)


class Checks(unittest.TestCase):
    def test_every_chart_up_to_five_then_more(self):
        text = "".join(f"<figure><svg><text>{n}%</text></svg></figure>\n\nNo link.\n\n" for n in range(11, 19))
        rows = integrity.findings(text)
        charts = [r for r in rows if r.startswith("- Chart (line ")]
        self.assertEqual(len(charts), 5)
        self.assertIn("- +3 more charts", rows)
        self.assertIn("(line 1)", charts[0])
        self.assertIn("(line 5)", charts[1])

    def test_every_frontmatter_key(self):
        rows = integrity.findings('---\ndescription: "50% off"\ntldr: "$300 saved"\n---\n\nNo link.\n')
        self.assertEqual([r.split(":")[0] for r in rows[:2]], ["- Frontmatter `description`", "- Frontmatter `tldr`"])

    def test_currency_codes_and_symbols_are_statistics(self):  # extraction's currency forms
        for value in ("AUD 300", "450 GBP", "USD20", "1.2m EUR", "A$300", "AU$1,200", "US$20", "NZ$9", "£450",
                      "€1.2m", "$5"):
            with self.subTest(value=value):
                rows = integrity.findings(f"> **TL;DR:** It cost {value} a year.\n\nNo link.\n")
                self.assertTrue(rows and rows[0].startswith("- TL;DR:"), rows)
                self.assertIn(value, rows[0])
                rows = integrity.findings(f'---\ndescription: "It cost {value} a year"\n---\n\nNo link.\n')
                self.assertTrue(rows and rows[0].startswith("- Frontmatter `description`"), rows)
                rows = integrity.findings(f"<figure><svg><text>{value}</text></svg></figure>\n\nNo link.\n")
                self.assertTrue(rows and rows[0].startswith("- Chart (line 1)"), rows)

    def test_one_currency_pattern(self):  # shared with extraction, never copied
        self.assertIs(extraction._CURRENCY, integrity.CURRENCY)

    def test_crlf_file(self):
        self.assertTrue(integrity.findings('---\r\ndescription: "50% off"\r\n---\r\n\r\nNo link.\r\n'))

    def test_internal_paths(self):
        for rel in (".plainspoken/reports/x.md", "a/.plainspoken/x.md", "post.claims.toml", "post.claims.json",
                    "post.reader-value.toml"):
            self.assertTrue(integrity.is_internal(rel), rel)
        self.assertFalse(integrity.is_internal("docs/post.md"))


if __name__ == "__main__":
    unittest.main()
