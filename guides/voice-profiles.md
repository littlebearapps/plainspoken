# Building a voice profile for everything you write

One profile can cover every kind of writing a person does: emails, posts, web pages, blog posts, reports and
proposals. This guide shows how to lay it out, where the evidence comes from, when to make a second profile, and
how to switch it on in each app. Field meanings are in `skills/voice/references/fields.md`;
`/plainspoken:voice build` follows these steps for you.

## Two layers

A profile has two layers.

**Layer 1 applies to everything.** `[identity]`, `[voice]` (principles, opinion pattern, humour, tone), `[reader]`,
`[avoid]`, `[lexicon]`, `[thresholds]` and `[[anchors]]` reach every skill, whatever the writing is. Put a habit here
when the author does it everywhere: "Starts with the answer", "Writes '&' for 'and'", "Times as 4pm, never 4 p.m.",
"Says 'I' for their own work, and 'we' only when it means them and the reader together".
Write a rule like that one with its context: a bare "never 'we'" would also ban the shared work the author does
say 'we' for.

**Layer 2 is per kind of writing.** `[blends]` and `[formatting]` each have four slots: `email`, `social`, `page` and
`article`. Drafting reads only the slot for the piece in hand (`profile --voice --type <kind>`), so a rule that only
holds for one kind goes in that kind's `formatting` line.

## Mapping your writing onto the four slots

There are only four slots, and plainspoken doesn't add more. Map each kind of writing onto the nearest one, and
name what it covers at the start of the line, so the reader of the profile (and the drafting skill) knows:

| Slot | Covers |
|---|---|
| `email` | Emails, replies, text messages, direct messages, chat replies |
| `social` | Posts on any social platform, short updates |
| `page` | Website pages, landing pages, one-pagers, product and service pages |
| `article` | Blog posts, reports, proposals, guides, newsletters, case studies, anything long |

When two kinds share a slot but differ a little, say both in the one line:

    article = "Blog posts, reports and proposals. The recommendation in the first paragraph. Reports: plain
    severity labels, no internal codes. Blog posts lean personal."

## Where the evidence comes from

Every principle, tone note and formatting line points at evidence, and nothing is guessed. Three kinds of evidence
count:

1. **Samples the author wrote themselves**, ideally five to ten across the kinds they write. These give the
   principles, the habits in `[lexicon]`, the rhythm (`run.py voice-stats`) and the anchors.
2. **Rules the author states**, in their own words: "I always put the answer first", "I never use dashes". Cite them
   with a date ("stated rule, 3 March").
3. **A style guide the author has approved**: a house voice guide, a brand guide's sample lines. Cite the section.

Leave out text an AI drafted, even if the author approved and published it. It would teach the profile the AI's
voice, not the author's. Anchors are always verbatim lines the author wrote or approved, with their source.
Anchors and samples are verbatim text, so keep anything taken from a client's material out of a profile you commit
or publish.

**When a kind has no samples**, fill its `formatting` line from the author's stated rules or style guide, give it no
anchors, and say so in a comment. Don't stretch habits from one kind onto another: a sign-off that's right for
email is wrong for a report. Note in `[rhythm]` which kinds it was measured on, and measure again when samples of
the other kinds arrive.

## Variations

Most people need one profile. Make a second one only when a kind of writing needs a different voice, not just
different layout: a formal voice for regulated clients, say, or a second brand.

- **Route it by folder.** `[engine] profiles` in `.plainspoken/config.toml` picks a profile by the file's path; the
  first match wins and `[engine] profile` covers the rest:

      [engine]
      profile = "me"
      profiles = [
        { glob = "proposals/**", profile = "me-formal" },
      ]

- **Drafts in chat get the main profile.** Text drafted in a conversation, or piped to `check -`, has no path, so
  it always uses `[engine] profile`. Only saved files are routed.
- **Profiles don't inherit.** A variant is a whole profile, so keep one master and copy the shared layer into the
  variant whenever the master changes (a short script, or a checklist), or the two will drift.

## Switching it on

The profile goes in `.plainspoken/profiles/<name>.toml` and is switched on with `[engine] profile = "<name>"` in
`.plainspoken/config.toml`, in each project folder the writing happens in. Check it with:

    python3 <plugin>/lib/run.py profile                    # first line names the profile in use
    python3 <plugin>/lib/run.py profile --voice --type email   # what drafting sees for one kind

- **Claude Code, Cowork, Codex:** the project you open.
- **Hermes Agent:** each Hermes profile's working folder, `terminal.cwd` in that profile's `config.yaml`. Hermes
  runs plugins outside that folder, but the hooks find the project from the file being written and the skills run
  their commands from the working folder, so both pick the profile up. Several Hermes profiles need a copy each.
- **`PLAINSPOKEN_PROFILE`** (a name or a full path) beats every project's config, so it suits a machine where all
  the writing shares one voice and no project has its own.

The user-wide `~/.config/plainspoken/config.toml` can't choose a profile: it holds only the nudge, drafting rule and
lint-after-edits switches (`/plainspoken:setup`).

## Limits to know

- `[thresholds]` set the checker's limits for files checked as articles. Anything checked as `social`, which
  includes every draft under 300 words piped to `check -`, gets the social limits instead (issue #104). To ban a
  character outright in short pieces too, add it to `[lexicon] extra_bans`.
- `[[registers]]` reach only `register-check`; drafting never sees them. Put anything drafting must follow in
  `formatting` as well.
- `knows` under `[reader]` isn't read by any skill yet.
