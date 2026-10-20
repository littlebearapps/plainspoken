# Retrodiction fixture

`ledger.jsonl` is a kaizen ledger backfilled from a host blog engine's rules v3: 18 articles, 14 of them published,
as of 2026-09-27, the day the host's owner made the v4 rule decisions that `tests/test_retrodiction.py` checks
calibrate against.

It holds no article text and no host paths. Each line is a v1 ledger event with:

- a doc id that hashes `article-<n>` (the article's place in a private manifest);
- span hashes and article hashes;
- facets: ruleset words (`term`), section kinds, 12f metric names, 7d forms and one override kind.

The only free text is the reason on the one override, which was recorded before the v4 decisions.

## How it was built

`scripts/dev/backfill_history.py` read a private manifest that isn't in this repo. The manifest named the host
engine's v3 lint report and the v3 text of each article, whether it was published, and that one override. For each
article the script:

1. parsed the text with plainspoken's `doc.parse` and the shipped default profile;
2. turned the old lint's BLOCK and WARN findings into `fired` events;
3. added `survived_publish` for every WARN span of a published article;
4. added the override as an `override` event.

The output went through `scripts/dev/leak_guard.py`.

## Known limits

- Facets come from plainspoken's parser. The host's v3 engine didn't check frontmatter FAQs (it only started to in
  v4), so the v3 history holds no FAQ evidence from them, and few spans carry `section = faq`.
- Only one override was recorded at the time. Fixes, justifications and judge verdicts from the v3 era aren't in the
  ledger. (The script now reads judge, justify and JR files, and takes `--profile-map` for per-domain profiles;
  this fixture predates both and was built without them.)
