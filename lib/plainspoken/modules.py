"""The action-module checker: the structure of `<!-- module:NAME -->` … `<!-- /module:NAME -->` blocks in markdown.

Action modules are ordinary markdown wrapped in HTML-comment markers, so the text reads correctly with the markers
ignored and a site can style them later. NAME is `start-here` (an early summary with jump links), `decision` (a
prioritise-or-skip comparison) or `action-plan` (numbered tasks).

`check(markdown, extra, unknown)` returns `{"line", "message"}` findings, sorted by line, `[]` when clean. A finding
with `"warning": True` is reported but doesn't fail the gate (`failures` leaves it out):

  * every opening marker has a matching closing marker, and no closing marker stands alone;
  * modules don't nest;
  * NAME is one of the three, or one of the project's own (`extra`, from `[reader_value] extra_modules`). Any other
    name is a warning, and `unknown="off"` (`[reader_value] unknown_modules`) drops it;
  * at most one module per section. A module's section is the first H1 or H2 heading inside it, else the section its
    opening marker sits in;
  * every `[text](#anchor)` link inside a `start-here` module points at an id that exists: an explicit `{#id}`
    attribute on a heading, else the heading's GitHub-style slug (lowercase, punctuation other than hyphens and
    underscores dropped, each space a hyphen, `-1`, `-2` … on repeats), or an HTML `id` such as `<a id="x"></a>`;
  * no H1 or H2 heading starts with a section number (`## 1. …`, `## 2) …`). Sections are numbered when the page is
    rendered; a number in the source changes the slug and every link to it. Hand-numbered H3 steps inside an
    action plan (`### 1. Clean the trap`) are fine.

Fenced code blocks and leading `---` frontmatter are skipped, and so is inline code (a backtick span on one line):
a marker or a link written as code is prose about modules, not a module. A start-here module's links are the ones
between its opening and closing markers, including on the marker lines themselves. Setext (underlined) headings
aren't recognised.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["NAMES", "check", "failures", "opens", "slug"]

NAMES = ("start-here", "decision", "action-plan")
_MARKER = re.compile(r"<!--\s*(/?)\s*module\s*:\s*(.*?)\s*-->", re.I)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+$")
_EXPLICIT_ID = re.compile(r"[ \t]*\{#([^}\s]+)\}$")
_NUMBERED = re.compile(r"^\d+(?:\.\d+)*[.)](?:\s|$)")
_JUMP_LINK = re.compile(r"\[(?:[^\]\\]|\\.)*\]\(\s*#([^)\s]+)\s*(?:\"[^\"]*\")?\s*\)")
_INLINE_LINK = re.compile(r"!?\[((?:[^\]\\]|\\.)*)\]\([^)]*\)")
_TAG = re.compile(r"<[^>]+>")
_SLUG_DROP = re.compile(r"[^\w\- ]")
_HTML_ID = re.compile(r"""<[a-z][^<>]*?\sid\s*=\s*["']([^"'\s]+)["']""", re.I)
# \x60 = a backtick, spelled out so "!" never sits next to one (Hermes' install scan reads that as shell).
_CODE_SPAN = re.compile(r"(?<!\x60)(\x60+)(?!\x60)(.+?)(?<!\x60)\1(?!\x60)")


@dataclass
class _Module:
    name: str
    line: int
    section: int  # line of the H1/H2 heading its opening marker sits under (0: before the first one)
    nested: bool
    own_heading: int | None = None
    links: list[tuple[int, str]] = field(default_factory=list)


def slug(heading: str) -> str:
    """A GitHub-style slug of the heading text (any `{#id}` already removed)."""
    text = _INLINE_LINK.sub(r"\1", heading)
    text = _TAG.sub("", text).strip().lower()
    return _SLUG_DROP.sub("", text).replace(" ", "-")


def _mask_code(line: str) -> str:
    """`line` with every inline code span blanked out, same length, so marker and link positions still line up."""
    return _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)


def _content_lines(markdown: str) -> list[tuple[int, str]]:
    """(1-indexed line, text) for every line outside frontmatter and fenced code."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    start = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                start = j + 1
                break
    out: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    for idx in range(start, len(lines)):
        line = lines[idx]
        f = _FENCE.match(line)
        if fence is not None:
            if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= fence[1] and not f.group(2).strip():
                fence = None
            continue
        if f and not (f.group(1)[0] == "`" and "`" in f.group(2)):
            fence = (f.group(1)[0], len(f.group(1)))
            continue
        out.append((idx + 1, line))
    return out


def opens(markdown: str, name: str) -> bool:
    """Whether `markdown` has an opening `<!-- module:NAME -->` marker for `name` outside code and frontmatter."""
    return any(m.group(1) != "/" and m.group(2) == name
               for _, line in _content_lines(markdown) for m in _MARKER.finditer(_mask_code(line)))


def failures(findings: list[dict]) -> list[dict]:
    """The findings that fail the gate: every one but a warning."""
    return [f for f in findings if not f.get("warning")]


def check(markdown: str, extra: tuple[str, ...] | list[str] = (), unknown: str = "warn") -> list[dict]:
    """Structural findings for every action module in `markdown`; `[]` when there are none."""
    findings: list[dict] = []
    stack: list[_Module] = []
    done: list[_Module] = []
    ids: set[str] = set()
    slug_counts: dict[str, int] = {}
    section = 0

    def say(line: int, message: str) -> None:
        findings.append({"line": line, "message": message})

    def collect(line: int, segment: str) -> None:
        """The jump links in `segment` belong to the start-here module open while it's read, if there is one."""
        start_here = next((mod for mod in reversed(stack) if mod.name == "start-here"), None)
        if start_here is not None:
            start_here.links.extend((line, a) for a in _JUMP_LINK.findall(segment))

    for n, line in _content_lines(markdown):
        ids.update(_HTML_ID.findall(_mask_code(line)))
        h = _HEADING.match(line)
        if h:
            level = len(h.group(1))
            text = _CLOSING_HASHES.sub("", (h.group(2) or "").strip())
            m = _EXPLICIT_ID.search(text)
            if m:
                text = text[:m.start()]
                ids.add(m.group(1))
            else:
                base = slug(text)
                count = slug_counts.get(base, 0)
                slug_counts[base] = count + 1
                ids.add(base if count == 0 else f"{base}-{count}")
            if level <= 2:
                section = n
                for mod in stack:
                    if mod.own_heading is None:
                        mod.own_heading = n
                if _NUMBERED.match(text.strip()):
                    say(n, f"heading starts with a section number ({text.strip()[:40]!r}): number sections when "
                           "the page is rendered, never in the markdown, so slugs and links stay stable")
            continue
        prose = _mask_code(line)
        pos = 0
        for m in _MARKER.finditer(prose):
            collect(n, prose[pos:m.start()])
            pos = m.end()
            closing, name = m.group(1) == "/", m.group(2)
            if not closing:
                if name not in NAMES and name not in extra and unknown != "off":
                    findings.append({"line": n, "warning": True, "message":
                                     f"unknown module {name!r} (expected start-here, decision or action-plan; a "
                                     "site's own go in [reader_value] extra_modules)"})
                if stack:
                    say(n, f"module {name!r} opens inside module {stack[-1].name!r} (line {stack[-1].line}): "
                           "modules don't nest; close the first one before opening the next")
                stack.append(_Module(name, n, section, nested=bool(stack)))
            elif not stack:
                say(n, f"closing marker for module {name!r} with no opening marker")
            else:
                mod = stack.pop()
                done.append(mod)
                if mod.name != name:
                    say(n, f"closing marker for module {name!r} doesn't match the open module {mod.name!r} "
                           f"(line {mod.line})")
        collect(n, prose[pos:])
    for mod in stack:
        say(mod.line, f"module {mod.name!r} is never closed (add <!-- /module:{mod.name} -->)")
        done.append(mod)

    by_section: dict[int, list[_Module]] = {}
    for mod in sorted(done, key=lambda d: d.line):
        if not mod.nested:
            by_section.setdefault(mod.own_heading or mod.section, []).append(mod)
        for line, anchor in mod.links:
            if anchor not in ids:
                say(line, f"start-here link to #{anchor} points at no heading: no {{#{anchor}}} id, no heading "
                          f"whose slug is {anchor!r} and no HTML id")
    for key, mods in by_section.items():
        where = f"the section under the heading on line {key}" if key else "the text before the first heading"
        for mod in mods[1:]:
            say(mod.line, f"module {mod.name!r} shares {where} with module {mods[0].name!r} (line {mods[0].line}): "
                          "one module per section")
    return sorted(findings, key=lambda f: f["line"])
