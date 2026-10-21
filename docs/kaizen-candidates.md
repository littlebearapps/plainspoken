# Kaizen candidates

Observations that may become rule or data changes. Nothing here changes the ruleset: a change needs evidence from
the kaizen ledger, a proposal and a recorded human approval (`kaizen apply`). Each entry is shaped so it can be
filed as a GitHub issue with the `kaizen` label.

The loop that acts on them ships in v0.5.0 (capture, `kaizen calibrate`, approval, `kaizen apply`; see
[guides/kaizen.md](../guides/kaizen.md)). A production host now records a real ledger; K1 to K4 wait for its first
calibrate runs, and go through a proposal and a recorded approval like any other change. K5 is a tooling note, not a
rule change.

## K1: the fixer edits to the 12f thresholds

- **Labels:** kaizen, metric
- **Seen:** Phase 2 end-to-end run (2026-10-10), with rule 12f open.
- **What happened:** during a fix pass, the fixer read the 12f thresholds and edited the article until the numbers
  passed. The edits were removal-only, so no rule was broken, but the target was the metric rather than the reader.
- **Why it matters:** anti-Goodhart: a pass rate that rises while readers notice no difference is a
  failure to investigate.
- **Candidate change:** give the fix pass the failing evidence spans only, never the numeric thresholds; keep 12f
  at WARN; measure 12f fixes against reader results once the blind reader test runs (its tier-2 run is a v1.0.0 item and
  needs samples of the author's own writing).
- **Decision needed:** none until the ledger has 12f data.

## K2: word-level data from the intake sources

- **Labels:** kaizen, data
- **Seen:** Phase 3 intake (2026-10-12): the source watch-outs and localisation files carry word tables (plain
  Australian swaps, overclaim verbs, agency soft-words, US regionalisms).
- **Why not now:** word lists belong to the checker, never drafting prompts, and the ruleset changes
  only through `kaizen apply` with evidence.
- **Candidate change:** propose them as `data/rules.toml` / `data/locales/en-AU.toml` entries through calibrate, each
  checked against the golden set for false positives. The tables are not kept in the repo; they're re-derived from
  the author's own source files when the proposal is written.
- **Informal terms to include:** from the localisation source, in three tiers. Usually fine in casual business
  writing: local, tradie, catch-up, sort out, stay across it. One at a time, never stacked: no worries, reckon,
  heaps, sorted. Usually avoid in professional writing: g'day, fair dinkum, she'll be right.
- **Compound forms to include:** also from the localisation source, and formerly a section of
  `guides/locale-en-AU.md`. The verb is two words and the noun or adjective is hyphenated (set up / set-up, clean
  up / clean-up, kick off / kick-off); the closed forms "setup" and "cleanup" are flagged in prose unless they're
  part of a name. It's word-level data, so it belongs to the checker, not the guide.
- **Decision needed:** at the first calibrate run on a real ledger.

## K3: word-level data in the copy-audit sources

- **Labels:** kaizen, data
- **Seen:** Phase 3 intake (2026-10-12): the source anti-tells catalogue and the outcomes-led document carry word
  lists (buzzwords, overclaim verbs, soft words) that copy-audit doesn't restate.
- **Why not now:** word lists belong to the checker; the ruleset changes only through `kaizen apply`.
- **Candidate change:** fold them into the K2 proposal at the first calibrate run on a real ledger, checked against
  the golden set. They're re-derived from the author's own source files; they aren't kept in the repo.
- **Decision needed:** at the first calibrate run on a real ledger, together with K2.

## K4: rules 7d and 7b against the write skill's own guidance

- **Labels:** kaizen, metric
- **Seen:** Phase 3 end-to-end run of `write` (2026-10-12, `docs/acceptance/p3-e2e.md`, "Surprises"), from the
  model's own kaizen notes.
- **What happened:** rule 7d (staccato: a section with no sentence over 25 words) pushed the model to pad two
  sentences for a Year 7 reader just to clear the counter. Rule 7b (press-release opener) flagged the answer-first
  opening that `skills/write/references/answer-first.md` asks for. The fix pass cleared both, so the run passed,
  but the shipped guidance and the checker pulled in opposite directions.
- **Why it matters:** a writer who follows the skill's own advice shouldn't get a WARN for it, and padding to beat a
  counter is the K1 anti-Goodhart failure again.
- **Candidate change:** collect 7d and 7b dismissals on answer-first openings and low-floor readers in the ledger.
  If the evidence holds, narrow 7b so a plain answer in the first paragraph isn't a press-release opener, and give
  7d a reader-floor knob (or keep it WARN-only for low floors). Either goes through `kaizen apply`.
- **Decision needed:** at the first calibrate run with 7d and 7b evidence.

## K5: a weekday check the drafting skills can run

- **Labels:** kaizen, tooling
- **Seen:** the same Phase 3 `write` run. The model saw that a date in the notes didn't fall on the weekday they
  named, tried to confirm it with `python3 -c "import datetime; …"`, and the call was refused ("This command
  requires approval"): the skill's allowed tools cover `run.py` only, by design. It left the year out and said so.
- **Why it matters:** dates are claims. A model that can't check a weekday either guesses or leaves it to the
  writer, and the second is right only if it says so every time.
- **Candidate change:** a `run.py` subcommand that prints the weekday for a date, covered by the existing grant, so
  no skill needs a wider one. Or record that the claims ledger is where a weekday gets checked, and leave it there.
- **Decision needed:** whether it's worth a subcommand; the owner decides at the next kaizen review.

## K6: rule 12f below article length

- **Labels:** kaizen, metric
- **Seen:** pre-v1.0 eval campaign, round 4 (#25): the 2+-trips WARN fired on 9 of 9 pieces of 300–500 words.
- **Done (2026-10-21):** the opening-repetition limit now adds 3/n (`data/RULESET-CHANGELOG.md`, engine change).
- **Still open:** paragraph SD isn't length-biased but sits on its limit: whole long posts had a median of 26
  against 25, and 300- to 1,000-word windows of them tripped it 56–69% of the time. Prose extracts from
  human-written technical READMEs trip the 2+-trips WARN at every length (19 of 21 over 1,000 words). Both need
  ledger evidence before any threshold moves.
- **Decision needed:** at the first calibrate run with 12f evidence, together with K1.
