# Claims and reader value

This guide is for anyone who wants a piece to be honest about what it says and what it gives the reader. It covers
the claims skill, the reader-value skill, the integrity hook, the CLI commands underneath them and their settings.

Both skills are manual: they run only when you call them. `write` uses both. It runs the reader-value outline
before it drafts, and the claims skill on the saved draft.

    /plainspoken:reader-value outline drafts/hot-water.md   # the contract, before drafting; parks a piece with no honest benefit
    /plainspoken:reader-value deliver drafts/hot-water.md   # an isolated reviewer: does the draft deliver the contract?
    /plainspoken:claims drafts/hot-water.md                 # claim ledger + pinned passages + the isolated claims checker

## Claims

The claims skill checks every number, quote, name and date in a draft against sources you've saved.

It never fetches anything. You save each source's text under `.plainspoken/sources/` (the `sources_dir`), and
`claims pin` finds the passage in it or refuses. To pin a claim is to tie it to the exact passage in a saved source
that supports it. A source outside that folder, or the article itself, never counts.

The ledger is the file that lists each claim and its status: `.plainspoken/claims/<key>.claims.toml`, or
`.claims.json` (`python3 <plugin>/lib/run.py paths <draft>` prints its path). It holds one status per claim. Only
`claims status` says PASS, and only after the isolated `claims-checker` agent has reviewed the current article and
ledger. A changed article or ledger means INCOMPLETE until it's checked again.

## Reader value

The reader-value contract says what the reader gets from the piece. It lives at
`.plainspoken/reader-value/<draft stem>.reader-value.toml`. Outline mode writes it before drafting, and parks the
piece when one of its fields can't be filled honestly.

In deliver mode the isolated `delivery-checker` agent reads the draft against that contract in a fresh context, and
`reader-value deliver` records its verdicts in `<key>.delivery.json`, bound to the draft, contract and rubric hashes.
Only that reviewer's reply can make the result PASS.

Where no subagent can run, the writer's own reading is recorded as a self-check (`--reviewer self-check`). It keeps a
FAIL, and a PASS reading becomes INCOMPLETE. `reader-value status` reads the record back: STALE once the draft,
contract or rubric has changed, and PASS only for a current pass from the isolated reviewer.

## The CLI underneath

The skills call these subcommands (`python3 lib/run.py <subcommand>`; each prints its own `--help`):

- `claims hash | stamp | validate | candidates | gaps | pin | recheck | scaffold | status | checker-input | record`:
  hash the article, write its hash and the time into the ledger, validate a ledger, list the values and quotes in an
  article and the ones the ledger misses, pin a passage in a saved source, recheck every pin offline, write a starter
  ledger, report the status, print the checker's input, and record its reply.
- `reader-value validate | modules | template | deliver-input | deliver | status`: validate a contract, check an
  article's `<!-- module:NAME -->` blocks, print a starter contract, print the delivery reviewer's input, record its
  reply, and read the delivery record back against the current files.
- `status <draft>`: the last saved check and claims status lines, the ledger's claims that need the owner, the
  draft's word count (as the check counts it) and the reader-value contract path. It reads them back without running
  or writing anything, so `write`'s report can quote them. A check or claims step that never ran, or ran on an older
  version of the draft, shows as INCOMPLETE. It exits 0 only when both say PASS.

## The integrity hook

After each Write or Edit of a target file, a hook flags prominent numbers that nothing sources: a statistic in a
chart, in the `> **TL;DR:**` block or in the frontmatter description with no link to a source. (Frontmatter is the
block of settings between `---` lines at the top of a Markdown file.)

For your own data, mark it as yours:

- an `<!-- integrity:allow -->` comment inside or beside the chart, or just above the TL;DR (a marker inside a chart
  covers that chart, never the TL;DR);
- or `# integrity: allow` in the frontmatter;
- and a `first_hand` claim in the ledger.

When the file has a claim ledger, the hook lists the ledger's gaps instead. It says nothing when there's nothing to
flag, and in warn mode it repeats itself only when a file's result changes.

A Bash hook refuses a shell command that writes a judge or checker reply, or a claim ledger, including through a
script it runs by name: those go through the Write and Edit tools. Reading them is fine.

## Settings

All three go in `.plainspoken/config.toml`:

    [claims]
    ledger_dir = ".plainspoken/claims"     # relative to the project root
    sources_dir = ".plainspoken/sources"   # where saved source text lives
    regulated_matrix = "docs/regulated-claims.md"  # your own regulated-claims list; unset means none (the plugin ships none)
    platforms_extra = ["Acme Portal"]      # platform names to treat as claims, on top of the shipped list

    [reader_value]
    cta_phrases = ["book a site visit"]    # your own calls to action, which can never count as reader value

    [integrity]
    mode = "warn"                          # off | warn (the default) | block
    paths = ["content/**/*.md"]            # files the hook checks; unset means the targets option, else **/*.md

`block` returns a block decision on every edit while findings remain: the edit is saved, and Claude is told to fix
it before going on. In Hermes Agent, `block` works as a warning, because Hermes can't hold the edit back
([hosts/hermes.md](../hosts/hermes.md)).

Every claims and reader-value report file is listed in [docs/report-contract.md](../docs/report-contract.md). The
rest of the settings: [guides/configuration.md](configuration.md).
