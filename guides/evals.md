# Evals: measuring whether plainspoken helps

The checks can only claim what they've been measured to do, so this guide covers the evals that measure them, what
each one costs and the rules that keep the numbers honest. Every eval command prints its own `--help`; the CLI is
`python3 lib/run.py eval …`.

## What each eval measures

| Eval | Question it answers | Command | Cost |
|---|---|---|---|
| Golden set | Is the labelled test data well formed, and is it still held out? | `eval golden validate` | free |
| Judge validation | Does each judge model find the tells a person would, and leave clean text alone? | `eval judges`, then `eval judges-report` | subscription or paid |
| Claims-checker validation | Does the claims checker block the claims a person would, and pass the sound ones? | `eval claims` | subscription |
| Rewrite graders | Does one rewrite keep its facts, drop the banned words and stay under the em-dash cap? | `eval rewrite DRAFT --source FILE` | free |
| Trigger cases | Do the skills start when a request fits, and stay quiet when it doesn't? | `claude plugin eval . --tag trigger` | paid |
| Rewrite cases | Are rewrites made with the plugin better than rewrites made without it? | `claude plugin eval . --tag rewrite` (a plain request) and `--tag rewrite-slash` (the same texts through `/plainspoken:humanize`) | paid |
| Rewrite delta | How many lint findings does each arm's rewrite still have? | `eval rewrite-delta RESULT` on a run made with `--keep-temp` | free |
| Smoke cases | Does every skill do its job end to end on a saved draft? | `claude plugin eval . --tag smoke` | paid |
| First engine call | Did each smoke run start with its skill's profile call? | `eval first-call RESULT` on a smoke run made with `--keep-temp` | free |
| Ablations | Does the output style, the session brief or a ban list in the prompt change the drafts? | `scripts/dev/draft_runs.py`, then `scripts/dev/ablation_table.py` | subscription |
| Blind reader test | Can a reader tell plainspoken's drafts from the author's own writing? | `eval blind build`, `form`, `run`, `score` | people: free; panel: subscription or paid |
| Lint pass rate | What share of a folder of drafts has no lint BLOCK? | `eval lint-rate --drafts DIR` | free |
| Verdict diff | Which lint verdicts on a fixed public corpus does a change move? | `scripts/dev/verdict_diff.py OLD NEW` | free |
| Anti-Goodhart report | Is the lint pass rate rising while readers notice nothing? | `eval goodhart` | free |

The judge report gives each group's true-positive rate (TPR: the share of real tells found) and true-negative rate
(TNR: the share of clean passages left alone), each with a 95% interval. The accept bar is 0.8 for both, on every
group, for every model. None of the evals adds its numbers into one score: a single number invites tuning the number
rather than the writing.

## Free, subscription and paid

- **Free** means no model is called: the golden-set check, the rewrite graders, the lint rate and the goodhart report.
  CI runs the unit tests for all of these on every pull request, validates the golden set with
  `eval golden validate --require-counts`, and posts the verdict diff (below). The lint rate and the goodhart report need drafts and history, so you run
  them yourself.
- **Subscription** means `claude -p` on a Claude plan. Nothing is billed, but each run uses the plan's quota, and the
  CLI reports a notional cost (what the same tokens would cost through the API). A full `write` run with its check is
  about US$1.7 to 5.4 notional per draft on Opus, so an ablation over a few briefs and arms uses a lot of quota.
- **Paid** means billed: the OpenRouter panel models, and every `claude plugin eval` run (each case starts real Claude
  sessions on your own credential; in CI, the API key).

The owner of the account OKs each paid run before it starts. The CLI can't know whether that has happened, so it asks
for `--yes` on billed calls and stops at `--max-cost-usd` (default 5). Neither replaces asking.

## The model panel and its key

`evals/panel.toml` lists the judge and reader models: `claude-opus` runs through the `claude` CLI on the subscription,
and six models from other vendors run through OpenRouter, one per family, so the results don't rest on one vendor's
models. `glm`, `openai`, `gemini`, `deepseek` and `glimmer` are the default five (picked for writing quality per
dollar); `grok` is an optional sixth. The OpenRouter key comes from the environment variable the file names
(`OPENROUTER_API_KEY`). It is read when a call is made and never written to a run file, the history or an error
message.

Every OpenRouter request carries the panel's privacy routing. `data_collection = "deny"` (the default) skips providers
that may store prompts, and the shipped panel also sets `zdr = true`, which allows only zero-data-retention endpoints.
That matters for the blind test, which sends your own writing. A model with no such endpoint fails its calls with
OpenRouter's message, and the run records them as errors. A model can override the panel's `zdr`: the shipped panel
sets `zdr = false` for `openai`, whose only zero-retention host refused a harmless prompt in the pilot, so OpenAI
calls take its normal route (still no training; short retention). A model can also be limited to some judge groups
with `groups = ["J1", "J2", ...]`: it gets no jobs for the other groups, and the report shows those as "doesn't
judge", never as errors. The shipped panel limits `openai` to J1–J4, because when an account enforces zero retention
its only route is Azure, which refuses every JR prompt.

The two transports don't sample alike. OpenRouter calls go out at `temperature: 0`; `claude -p` has no temperature
flag, so the `claude-cli` models answer at the CLI's default sampling, and one case can flip between runs. Each judge
and blind run records every transport's sampling in its summary (`summary.json`, `score.json`) and its report header.
Run-to-run variance isn't comparable across transports: compare a Claude model's stability with its own earlier runs,
not with an OpenRouter model's.

Model slugs and prices drift. Before a run, check the file against OpenRouter's catalogue (one free request, no key):

    python3 lib/run.py eval panel check

## Running a paid eval: dry run, OK, then `--yes`

1. Run the command with `--dry-run`. It prints the estimate per model and the billed total, sends nothing and writes
   nothing.
2. Show the estimate to the owner and get an OK for that run.
3. Run it again with `--yes` (and a `--max-cost-usd` below the OK'd amount). Before each call the runner adds the
   spend already recorded to the next call's estimate, and stops cleanly when that would pass the cap. There is
   one budget per batch: the stop also holds back the `claude-cli` calls not yet started, though they bill nothing,
   so the run stays one partial state that a re-run with the same `--out` finishes.

```bash
python3 lib/run.py eval judges --models claude-opus,deepseek,gemini --dry-run
python3 lib/run.py eval judges --models claude-opus,deepseek,gemini --yes --max-cost-usd 3
python3 lib/run.py eval judges-report --run .plainspoken/evals/judges-<time>
```

A run that stops early, or gets interrupted, resumes when you re-run it with the same `--out`: every reply already in
`replies.jsonl` is skipped. A model reply that isn't the JSON asked for counts as an error, never as a pass or a fail.

`claude plugin eval` has no dry run. Estimate it from the last run: the trigger suite's 28 cases at one run each cost
US$3.51 on 2026-10-14, and the rewrite suite runs every case twice (with and without the plugin). Every run here uses
`--no-publish --max-cost-usd 5 --threshold 0.8 --trust-plugin`. The ceiling is checked before each run launches, so
one invocation can spend about US$5 plus the runs already in flight (up to 4 with `-j 4`), and the workflow's `all`
suite, two invocations, about twice that:

```bash
claude plugin eval . --tag trigger --ablation none --allow-tools "Bash(python3 *)" --runs 1 -j 4 \
  --no-publish --max-cost-usd 5 --threshold 0.8 --trust-plugin
claude plugin eval . --tag rewrite --runs 2 -j 3 --keep-temp \
  --no-publish --max-cost-usd 5 --threshold 0.8 --trust-plugin --json rewrite.json
python3 lib/run.py eval rewrite-delta rewrite.json
claude plugin eval . --tag rewrite-slash --runs 2 -j 3 --keep-temp \
  --no-publish --max-cost-usd 5 --threshold 0.8 --trust-plugin --json rewrite-slash.json
python3 lib/run.py eval rewrite-delta rewrite-slash.json
claude plugin eval . --tag smoke --ablation none -j 2 --keep-temp --json smoke.json \
  --allow-tools Bash Write Edit --no-publish --max-cost-usd 15 --threshold 0.8 --trust-plugin
python3 lib/run.py eval first-call smoke.json
```

The rewrite cases' regex graders only pass or fail, and a strong model passes most of them without the plugin, so
`eval rewrite-delta` reads each run's final reply from its kept trace and counts the lint's BLOCK and WARN findings per
arm. The delta is without minus with: positive favours the plugin. `--keep-temp` is what keeps the traces; without it
every run is listed as missing. It also counts new numbers, in digits or in words, that the source (the pasted
passage, or a drafting case's brief) doesn't have. A number worked out from the source's own (150 for 151, a sum, or
"seven in every ten" for 151 of 212) is listed as derived and not counted; the rules are in `rewrite.py`. The smoke cases run each skill once through its slash command on a draft the case
saves first, including the full check with its four judges, so they cost more than the trigger suite (about
US$5 for all twelve on 2026-10-21). On Claude Code 2.1.306 the eval sandbox couldn't run the skills' old load-time
commands (see `docs/acceptance/v0.7-drafting-hooks.md`), so the slash and smoke suites ran on 2.1.303 there.
Since #12 each skill runs that call as its first step instead, which should lift the pin; until a slash and smoke
run on the current CLI confirms it, keep using `npx @anthropic-ai/claude-code@2.1.303 plugin eval …`. Run one CLI
version at a time: two at once on one login revoked a token mid-run.

Each smoke case except `setup`, which has no profile step, also has a `*-first` grader: the run's first
`run.py` call must be the skill's first step, `run.py profile` (`run.py kaizen review` for kaizen). When it fails, the
runner says only "pattern not found in trace", so run the suite with `--keep-temp` and `--json`, then `eval first-call`
on that file: it prints the first engine call of each run.

The trigger suite uses `--ablation none` because a `tool_used: Skill` grader isn't scored against a no-plugin arm. The
rewrite suite keeps the default with-without ablation, which adds the no-plugin arm and reports the difference. The
same two suites run from GitHub through the manual `evals` workflow (`.github/workflows/evals.yml`), which skips with
a notice when the repository has no `ANTHROPIC_API_KEY` secret. This repository doesn't set one, so here the workflow
skips; run the suites locally, or from a fork that adds its own key. Pull requests never need it.

## Claims-checker validation

The CL group of the golden set (`evals/golden/CL.toml`) holds short articles with their ledgers, and says for each
ledger claim whether the claims checker should block it. `eval claims` puts every CL case to the checker's rubric on
one Claude model through `claude -p`, then reports per case which claims it got right, and overall the accuracy, the
share of claims it should block that it did (TPR) and the share it should pass that it did (TNR). A claim counts as
blocked when the reply files a `blocking` finding against it; a warning is still a pass. It runs on Claude only, so
nothing is billed, but it stops before the notional cost the CLI reports would pass `--max-cost-usd` (default 1).
Dry-run it first: it prints each case's estimate and sends nothing.

```bash
python3 lib/run.py eval claims --model claude-opus-5-5 --dry-run
python3 lib/run.py eval claims --model claude-opus-5-5 --max-cost-usd 1
```

Re-run with the same `--out` to resume a stopped run or retry a failed call. File each miss the report lists; never
fix the rubric to catch a held-out case (below).

## The golden set and its labels

The golden set (`evals/golden/`) is the labelled text the judges and the claims checker are measured against. Each
case records who decided its label:

- `confirmed`: a person labelled it directly;
- `endorsed`: a person approved it indirectly, for example by approving the fix that removed the tell;
- `provisional`: built for the set and not yet checked by a person.

Most cases start provisional, and the same family of models that is being measured helped build them. Until a person
confirms them, read the judge numbers as an upper bound. The report shows the confirmed and endorsed cases and the
whole set separately, and labels the whole-set figure a proxy.

To confirm a case, read it, decide whether the label is right, and edit it in place: set `status = "confirmed"` and
`source = "owner"` (fix `label` first if it's wrong), or delete a case that's ambiguous. Then run
`eval golden validate`. The file format is in `evals/golden/README.md`.

## Held-out data: never tune against it

The golden set and the blind-test pairs are held out. They measure the checks; they are never used to improve them.

- No case text, no JR `reason` and no CL claim prose is quoted in a rubric, skill, guide, hook, output style, template
  or mining brief.
  `eval golden validate` fails when a file there shares a run of 8 or more words with a case, or holds the whole of
  one shorter than 8 words, and when it can't read a folder or file there (`evals/golden/README.md`).
- A label never goes into a prompt.
- A blind-test folder carries a `.heldout` marker, and `kaizen mine` refuses to read it.
- When a judge misses a case, don't edit the rubric to catch that case. Fix the rubric only from evidence outside the
  held-out set (the kaizen ledger, new examples written fresh), then measure again.

## The verdict diff

`scripts/dev/verdict_diff.py OLD NEW` lints one fixed public corpus with two versions of the plugin and lists every
text whose lint status (BLOCK, WARN or CLEAN) or finding count per rule moved. OLD and NEW are git refs or checkout
folders. The corpus is read from NEW, so both sides lint the same texts: every case in `evals/golden/` plus the
rewrite references and the voice samples, 268 texts as of 23 October 2026. It runs the lint only, with the default
profile. No model is called, and nothing is written into the repo. It takes about 10 seconds.

On every pull request CI runs it base against head and writes the markdown to the job summary. It never
fails the build: a rule change is meant to move verdicts, and a person reads the list to see whether the right ones
moved. For a release, paste the output for the range into the release PR:

```bash
python3 scripts/dev/verdict_diff.py v0.12.0 HEAD           # markdown; --json for the full record
```

The report names texts by path and case id, never by their words or labels, and the held-out rule above still
applies: a golden case that moved is a reason to look at the change, never to tune a rule to that case.

## The blind reader test

The blind test asks whether a reader picks plainspoken's draft as the person's writing about as often as the person's
own. You supply matched pairs: a piece the author wrote, and a plainspoken draft from a neutral brief on the same
subject.

    python3 lib/run.py eval blind build --spec pairs.toml --out blind/ --seed 7
    python3 lib/run.py eval blind form --out blind/

`build` strips both texts to plain paragraphs and cuts each to roughly the same length (the shortest run of whole
sentences with at least N words, `--words`), so format and length don't give the author away. It also counts a small
fixed list of spelling markers (-ise/-ize, -our/-or, -re/-er, doubled l) on each side and records them in
`build.json`. When a pair still differs in length by more than 15%, or one side spells AU/GB and the other US, it
refuses: it names the pair, exits 1 and writes nothing. A side with no markers, or with both kinds, is allowed.

- **Tier 1, people.** `form` writes `form.md` and `answers.csv`. The author sends the form to readers and collects
  their answers. The plugin never contacts anyone.
- **Tier 2, the model panel.** `eval blind run --models …` asks the panel every pair in both orders, and the score
  reports position bias (how often a model picks A). It's a proxy for people, and it follows the paid-run rules above.
  It exits 1 when a call failed; re-run it with the same `--out` to retry. Tier 2 means vendors other than Anthropic:
  judges favour their own family, and plainspoken's drafts are Claude-written. Claude models still get a row each, but
  the history line comes from the non-Anthropic majority (or the one non-Anthropic model), and when every tier-2 judge
  is Anthropic the score says so and adds no tier-2 line to the history.

`eval blind score --out blind/ --answers answers.csv` scores both tiers, with 95% intervals. A pair and order with no
reply or answer yet is counted as missing, apart from the errors (a failed call, a reply that isn't the JSON asked
for, a blank answer), and a reply whose key isn't a pair of this build is named in a warning, not scored. A model
counts as Anthropic by the model that answered (the CLI's `opus`, `sonnet` and `haiku` aliases included).

## Ablations

`scripts/dev/draft_runs.py` drafts the same briefs under five arms: `none` (the plain model), `plugin`, `plugin+style`
(the output style on), `plugin+brief` (the session brief on) and `plugin+banlist` (the ban list added to the drafting
prompt, for this test only). `scripts/dev/ablation_table.py` grades the drafts with the engine. The plugin arms run
with `--setting-sources project,local`, so your own plugins, skills and CLAUDE.md don't load (project and local
settings still do), and the comparison doesn't measure your setup.

Every brief must carry its own facts. The `write` skill stops and asks when a brief wants facts it doesn't have, where
the plain model makes them up. That's the plugin working, but it leaves the arm with no draft to compare.

## The history and the anti-Goodhart report

`eval judges`, `eval judges-report`, `eval blind score` and `eval lint-rate` each add a line to
`.plainspoken/evals/history.jsonl` (`judges-report` skips a run and `--min` the history already holds).
`eval goodhart` reads it and flags when, between two blind runs, the lint pass rate on their drafts rose by 0.10 or
more while readers' results didn't improve: the two intervals overlap, or the later one sits entirely below the
earlier. A blind score with no valid judgement adds no line. A flag means the lint may be rewarding its own patterns
rather than better writing. Investigate the rules that changed; don't tune against the held-out set to make the flag
go away.
