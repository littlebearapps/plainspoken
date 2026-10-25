# Checking and rewriting a draft

This guide is for anyone who wants to know what happens when plainspoken checks, rewrites or drafts a piece of
writing. It explains the check step by step, what each result means, and what the other writing skills do.

- [How a check works](#how-a-check-works)
- [What the results mean](#what-the-results-mean)
- [Running a check](#running-a-check)
- [What a check reads](#what-a-check-reads)
- [Humanize](#humanize)
- [Write](#write)
- [Plain language and the cold reader](#plain-language-and-the-cold-reader)
- [The other language skills](#the-other-language-skills)
- [Always-on token cost](#always-on-token-cost)

## How a check works

    /plainspoken:check post.md

1. **Lint.** The lint is a fixed set of pattern rules that code runs on the text, so it gives the same result every
   time: banned words, em dashes over the limit, transitions, sentence rhythm and the like. Each finding is a BLOCK
   (must go), a WARN (fix it or give a reason) or a CANDIDATE, which a judge decides. Before the judges start, the check fixes lint findings in at most
   two lint-only passes, so the judges read a lint-clean draft.
2. **Four judges.** A judge is a separate model run that reads the draft in a fresh context. It never sees your
   session, never edits a file and returns its verdicts as JSON with the exact words it objects to. Each judge looks
   at one group of rules, for example:
   - J1, framing and meta: writing about the writing, scope disclaimers, unasked-for summaries, recycled
     conclusions, announcement openers;
   - J2, structure and rhythm: lists of three by habit, press-release openers, parallel constructions, forced
     balance, "from X to Y" ranges, synonym cycling, stock "challenges and future outlook" sections;
   - J3, register and claims: qualified uses of banned words, avoiding "is" and "has", hedging, unnamed sources,
     inflated stakes, patronising analogies, marketing uses of "optimise";
   - J4, sentence mechanics: "-ing" openers, no informality, trailing "-ing" clauses that fake depth, and three
     calibrations for narrative writing.
3. **Merge.** The engine combines the lint with the four verdicts and proves every rule was covered. You never score
   or merge anything by hand.
4. **Fix or justify.** Every BLOCK must be fixed. A failing WARN is fixed, or kept with a one-line reason. A fifth
   judge, JR, reviews each reason in a fresh context and accepts or rejects it.
5. **Up to two fix passes.** A fix pass cuts, joins or splits sentences, or restates plainly what's already there. A
   join uses "and" or "but", or merges two sentences; it never adds a clause, detail or reason. A fix never adds a
   fact, number, name, quote, example or opinion. After each pass the lint and all four judges run again, because the
   text changed.

The check writes its files to `.plainspoken/reports/` in the project you run it from. Every report file is listed in
[docs/report-contract.md](../docs/report-contract.md).

## What the results mean

| Result | Meaning |
|---|---|
| PASS | No BLOCK is left, and every failing WARN was fixed or kept with a reason JR accepted |
| FAIL | At least one BLOCK is still there after the fix passes |
| UNRESOLVED | No BLOCK, but a failing WARN was kept without an accepted reason. It's never a pass |
| INCOMPLETE | Something the merge needs is missing, out of date or unreadable: a judge's reply, the lint, or a file made with another profile or ruleset version. The check reruns what's missing once, without editing the draft |

Edit the draft after a check and the saved result goes stale: `status` then shows `INCOMPLETE (stale …)` until you
check it again.

## Running a check

    /plainspoken:check post.md
    /plainspoken:check thread.md --content-type social

- **Social posts.** `--content-type social` checks the text against the social limits instead of the article ones.
- **Findings only.** Ask for findings without edits and the check follows its report-only route: no fix passes, no
  humanize, and the file stays exactly as it is. You get the BLOCK and WARN lines and the result, and it says plainly
  that nothing was fixed.
- **A quick lint from stdin.** `python3 <plugin>/lib/run.py check -` lints a draft piped in on stdin and saves
  nothing. A draft under 300 words is checked as social, a longer one as an article.
- **A lint that leaves no trace.** `check --no-record` prints the lint and saves no report (unless `--out` names
  another file), no kaizen event and no snapshot. Use it for a quick look that shouldn't count as kaizen evidence.

The CLI finds the project root by itself (the nearest folder with `.plainspoken/config.toml` or `.git`), so you can
run it from anywhere in the project.

## What a check reads

A check reads the body plus the frontmatter keys listed in the profile's `[document] visible_frontmatter_keys`
(`title` and `description` by default). Frontmatter is the block of settings between `---` lines at the top of a
Markdown file. For a post or video, put the title, caption and alt text in the frontmatter and list their keys
there, or keep alt text inline in the body as `![alt](…)`.

The `read:` line under the lint heading (`fields_read` in the JSON) shows what the lint read. plainspoken checks only
the text it's given, never a platform's rendered version.

## Humanize

    /plainspoken:humanize post.md

Humanize rewrites a draft to remove AI writing patterns, without a full check. It works from 26 patterns, strongest
first, and keeps the writer's voice from the profile or a sample you give it. Its first rule is the same as the
check's: remove, never add. When a sentence needs a detail it doesn't have, it flags that for you instead of
inventing one. Used on its own, it may lint the result once and fix again once if a BLOCK remains. The check calls it
for its fix passes.

## Write

    /plainspoken:write notes.md

Write drafts a piece from your notes or a brief in the voice profile's style, then runs the full check. It goes in
this order:

1. **Research gate.** With no sources and no brief, it stops and asks. Facts come only from your sources, the brief
   or what you say in the session.
2. **Reader value.** It sets out what the reader gets from the piece before drafting, and parks a piece with no
   honest benefit ([guides/claims-and-reader-value.md](claims-and-reader-value.md)).
3. **Outline, then draft.** It writes headings from what each section says, reads the profile's anchor passages for
   each kind of section, and drafts one section at a time against them.
4. **Claims.** It builds the claim ledger for the saved draft and has the isolated claims checker review it.
5. **Check.** It runs the full check, and reruns the claims steps if a fix changed the draft.

Its report starts with the lines `python3 <plugin>/lib/run.py status <draft>` prints, copied exactly: the check and
claims results, the claims that need you, the word count and the reader-value contract path. Those come from the
engine, never from the model's memory. Before a drafted piece ships, run `/plainspoken:reader-value deliver <draft>`
to check it keeps the promise it made.

## Plain language and the cold reader

    /plainspoken:plain-language page.md             # audit: lists what the reader would miss, changes nothing
    /plainspoken:plain-language page.md --rewrite   # edits the file

Plain-language checks that someone outside the field understands the text on one read. The reader is the one your
voice profile names. It glosses or cuts insider terms (any word that reader wouldn't use). It never drops a caveat,
changes a number or softens a limit to make a sentence shorter, and never adds a fact.

For a text over about 600 words, or when you ask, it hands the text to the `cold-reader` agent. The agent reads it
once in a fresh context, as the reader your profile names, and reports in JSON where it got lost, which words it
didn't know and what it would do next. It never rewrites.

## The other language skills

These run only when you call them:

    /plainspoken:voice build samples/*.md                  # build a voice profile from your own writing
    /plainspoken:copy-audit hero.md                        # audit buyer-facing copy against the evidence
    /plainspoken:register-check email.md --kind follow-up  # flag a message that reads wrong for its kind (flags only)
    /plainspoken:adapt post.md linkedin bluesky            # draft platform versions of a post (drafts only, nothing is posted)

How to build and lay out a profile: [guides/voice-profiles.md](voice-profiles.md).

## Always-on token cost

The skill and agent descriptions sit in Claude's context in every session; that's the plugin's always-on cost.
Measured 2026-10-25 with Claude Code CLI 2.1.310, `python3 -m scripts.dev.token_budget .` reports 490 tokens, against
a budget of 500. Hooks add none.

That figure leaves out the nine manual-only skills (adapt, claims, copy-audit, doctor, kaizen, reader-value,
register-check, setup and voice, about 700 tokens together), because Claude Code keeps their descriptions out of
context ([docs/claude-code-facts.md](../docs/claude-code-facts.md) section 7). `claude --plugin-dir . plugin details
plainspoken` counts them in its `Always-on` line. Without `--plugin-dir`, `claude plugin details plainspoken` only
finds an installed copy.
