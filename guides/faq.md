# FAQ

Short answers to the questions people ask first. For a problem with a fix, see [troubleshooting](troubleshooting.md).

## Does plainspoken send my writing anywhere?

No. The lint runs as Python on your machine, and the judges and checkers are subagents of the app you're already
using, so your draft goes no further than it would in that app anyway. Two things reach outside, and only if you
switch them on: kaizen proposals go to a GitHub issue or a Trello card when you set `[kaizen] adapter` (the default
writes a file under `.plainspoken/kaizen/proposals/`), and the paid evals send their test cases to outside models
when you run one. Nothing is ever posted for you: `adapt` writes drafts only. What stays in your project is listed
in the README's [What stays on disk](../README.md#what-stays-on-disk).

## Will it change my facts?

No. A fix cuts, joins or splits sentences, or restates plainly, using only what your text already says, and it
never adds a fact, number, name, quote, example or opinion that isn't in the text or given by you. A tell that can't
be fixed by cutting stays flagged, and you decide.

## What do PASS, FAIL, UNRESOLVED and INCOMPLETE mean?

| Status | What it means |
|---|---|
| PASS | No BLOCK is left, and every WARN you kept has a reason the reviewing judge accepted. |
| FAIL | A BLOCK is still in the draft after the fix passes. |
| UNRESOLVED | No BLOCK is left, but a flagged WARN was neither fixed nor kept with an accepted reason. It's never a pass. |
| INCOMPLETE | An input is missing or stale, so the check can't give a result yet. |

More in [checking a draft](checking.md).

## Why did my check say INCOMPLETE?

Most often the draft, its profile or the ruleset changed after the judges read it, so their verdicts no longer
match the file. Rerun the check. If merge names a missing judge or a reply it refused, the check reruns that step
once; still INCOMPLETE after that, it stops and quotes the problem lines.

## How much of my context does it use?

The four skills that start on their own, and the five agents, have descriptions that sit in context all the time.
Together they come to about 500 tokens, measured with `python3 -m scripts.dev.token_budget .` against a budget of
500. The nine manual-only skills add nothing until you call them, because Claude Code keeps their descriptions out
of context. Hooks add none, unless you switch on the session brief.

## Can I stop the skills starting on their own?

Yes. Deny the Skill tool for each skill you want to keep manual in your project's `.claude/settings.json`, for
example `"deny": ["Skill(plainspoken:write)"]`. The model then can't start that skill by itself, but the slash command
still works whenever you type it yourself, and a skill that hands over to a denied one reads its steps instead. Details are in [configuration](configuration.md).

## Does it work in claude.ai or ChatGPT?

Only as paste-in text. Neither chat app has a shell, so the lint, the judges and the hooks can't run there.
`python3 lib/run.py setup --host claude-ai` (or `--host chatgpt`) prints a short writing rule to paste into the
app's preferences or a project's instructions. The model follows it as guidance, and a "check" in chat is the
model's own read, not plainspoken's.

## What's different in Codex and Hermes Agent?

The same skills, agents and engine run there, with a short host note the skills point to
([Codex](../hosts/codex.md), [Hermes Agent](../hosts/hermes.md)). The main differences:
- There's no kaizen backstop, so `kaizen report` shows 0 judge replies returned.
- There are no install-time settings: pick a profile with `[engine] profile` in `.plainspoken/config.toml`.
- Codex runs plugin hooks only after you trust them in `/hooks`, and since Codex 0.164.0 it asks again after every
  plainspoken update.
- In Hermes, the agents' read-only rule is an instruction they follow, not a sandbox.

## Can it write in my own voice?

Yes. Run `/plainspoken:voice build` on five to ten samples of your own writing, or copy
`templates/voice-profile.toml` to `.plainspoken/profiles/<name>.toml` and edit it. Then set
`[engine] profile = "<name>"` in `.plainspoken/config.toml`. One profile can cover everything you write, with the
habits that hold everywhere in its shared sections and a slot each for email, social posts, pages and articles. See
[voice profiles](voice-profiles.md).

## Which English does it check?

The checker doesn't depend on one. Its word lists catch both -ise and -ize spellings, so the lint and the judges give
the same result whichever English you write. The locale steers the drafting skills and the register check's spelling
item instead. It's Australian English unless you choose British or American (`en-AU`, `en-GB` or `en-US`) with the
`locale` plugin option, `[locale] variant` in a config file or a voice profile's `locale`
([configuration](configuration.md#which-english-the-skills-write-in)). For Australian wording beyond spelling, see
the [Australian English guide](locale-en-AU.md).

## Can I lint something without it counting toward kaizen?

Yes. Run `python3 lib/run.py check --no-record <draft>`, or ask the check skill for a quick lint that shouldn't
count as evidence, and it prints the lint without saving a report, a kaizen event or a snapshot of the draft. A
draft linted from stdin with `check -` records nothing either.

Both are for a quick look. A full check, with the judges, records as usual.

## Is the publish gate a security boundary?

No. It's a guardrail against pushing unchecked writing by accident. It looks at each push command and, when its
strictness is set to block, refuses the push unless every file it covers has a current PASS from a full check. It
has known gaps, listed in [Claude Code facts](../docs/claude-code-facts.md) section 6.

## A finding is wrong. How do I tell it?

Run `/plainspoken:kaizen dismiss post.md` and give your reason. That goes into the ledger, and enough dismissals of
the same rule lead kaizen to propose loosening it, which you then approve or reject before
anything changes. To report it upstream, open a [False positive issue](https://github.com/littlebearapps/plainspoken/issues/new/choose), with
`/plainspoken:kaizen report --share` for anonymised counts.

## Is it v1.0 yet?

No. plainspoken is before v1.0, so expect changes between releases. [CHANGELOG.md](../CHANGELOG.md) has each release,
and [ROADMAP.md](../ROADMAP.md) has what's next.
