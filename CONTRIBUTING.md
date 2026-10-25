# Contributing to plainspoken

Thanks for helping. plainspoken is made by Little Bear Apps and released under the MIT licence. This guide covers
setting up, the checks a change has to pass, and how the ruleset changes over time.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By taking part, you agree to keep to it.

## Before you start

You need:

- Python 3.11 or newer. The engine uses the standard library only, so there's nothing to install with pip.
- git.
- The `claude` CLI (Claude Code), to load the plugin for a session, validate the manifest and run the evals.

## Set up and check your work

    git clone https://github.com/littlebearapps/plainspoken.git
    cd plainspoken
    claude --plugin-dir .                 # load this copy for one session

Run these from the repository root before you open a pull request. CI runs the same checks.

    python3 -m unittest discover -s tests -t .              # unit tests (stdlib only, no model calls)
    python3 scripts/dev/leak_guard.py                        # no private names (see below)
    python3 scripts/dev/check_links.py .                     # relative links resolve inside the repo
    python3 scripts/dev/check_doc_commands.py .              # every command a doc names exists
    python3 scripts/dev/lint_frontmatter.py .                # skill and agent frontmatter
    python3 scripts/dev/check_release_version.py .           # the manifests agree on the version
    python3 lib/run.py eval golden validate --require-counts # the golden set is well formed
    python3 -m scripts.dev.token_budget .                    # always-on text stays inside its budget
    claude plugin validate . --strict                        # manifest and components

To lint one file the way the docs tests do:

    python3 lib/run.py check <file> --profile default --no-record

`--no-record` prints the lint and saves nothing, so a quick look doesn't count as kaizen evidence.

## Branches, commits and releases

Work happens on `main`, so branch from it (names like `fix/…`, `feature/…` or `docs/…`) and open your pull
request against `main`. The default branch, `stable`, holds the latest release only: the release workflow moves it
(`.github/workflows/stable.yml`), so never open a pull request against `stable`.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/), because release-please reads
them to cut releases and write the changelog. Before 1.0, a `feat:` commit makes a minor release and a `fix:`
commit makes a patch release. `feat`, `fix`, `perf`, `revert` and `docs` commits get a line in [CHANGELOG.md](CHANGELOG.md);
`chore`, `ci`, `test`, `build`, `style` and `refactor` don't. You don't edit the changelog by hand: write the
commit subject as the line a user should read.

    fix(check): say which rule a held-back finding belongs to
    feat(claims): accept a saved web page as a source
    docs: explain the report-only route

Keep each pull request to one change, with tests for new behaviour. Link the issue it fixes (`Fixes #N`).

## Rules for the docs

The docs are held to the same standard as the writing plainspoken checks, and tests enforce most of it:

- The README, everything in `guides/` and `docs/report-contract.md` pass plainspoken's own lint at the default
  profile with no BLOCK finding (for example, at most 3 em dashes a file and none of the banned words).
- The README keeps its `### What stays on disk` section and every file name in it.
- No word-count caps in the README or the guides.
- Every `run.py` command and flag named in the README, guides, host notes and skills must exist
  (`check_doc_commands.py`).
- Write in Australian English, in plain sentences, with sentence-case headings.

## The leak guard

The leak guard fails on any name that must never appear in the repo. `data/leak-denylist.txt` holds only generic
patterns; the names themselves live in a private list kept outside the repo, in the file `PLAINSPOKEN_LEAK_LIST`
points at. CI on this repo reads that list from a repository secret, fails when the secret is missing, and logs a
hit as `private#<line>`, never the name. A fork, a pull request from a fork or a local run without the variable
skips the private list with one notice line and checks the rest.

A name can also be stored as a keyed hash (HMAC-SHA256), so it never sits anywhere in plaintext. That's optional.
The key comes from `PLAINSPOKEN_LEAK_KEY` or a git-ignored `.leak-guard-key`; without it, a run that meets keyed
entries ends on `SKIPPED (no key)`, never a clean result. The guard doesn't scan git-ignored files, and
`python3 -m scripts.dev.leak_guard --help` lists the options. To hash or convert a name, pass `-` for the term
(`--convert -`): it's read from stdin, without echo at a terminal, so the name stays out of shell history and `ps`.

## Changing what the checks flag

If a rule fires on writing that's fine, misses a tell, or you'd like a new pattern added, use the matching issue
form: [False positive](https://github.com/littlebearapps/plainspoken/issues/new?template=false-positive.yml),
[Missed tell](https://github.com/littlebearapps/plainspoken/issues/new?template=missed-tell.yml) or
[Pattern proposal](https://github.com/littlebearapps/plainspoken/issues/new?template=pattern-proposal.yml).
Anonymise any text you paste.

Ruleset changes don't go in as ordinary edits. They go through the kaizen loop: a proposal with its evidence, a
person's `APPROVE:` line, then `kaizen apply`, which bumps the ruleset version and records who approved it in
`data/RULESET-CHANGELOG.md`. The [kaizen guide](guides/kaizen.md) explains each step. `kaizen report --share`
prints counts only, with no text, if you'd like to attach your numbers to an issue.

## Evals

The unit tests and the golden-set check are free and run in CI, but some evals call models and are billed, and
each paid run needs a maintainer's OK before it starts. Don't start one as part of a pull request; say in the pull request
what you'd like measured. The [evals guide](guides/evals.md) has the details and the dry-run step.

## Security problems and questions

Report a vulnerability privately, as [SECURITY.md](SECURITY.md) describes, never in a public issue. For questions
and help, see [SUPPORT.md](SUPPORT.md).
