# Phase 3 trigger evals

Date: 2026-10-14. Claude Code CLI 2.1.299, Linux, `claude plugin eval` against the local checkout on `main`
(Phases 3 and 4 merged; the plugin reported version 0.1.0 because the v0.2.0 release PR was still open). Paid
run, approved by the owner, capped at US$5.

Result: **28 of 28 cases passed, each at score 1.00, for US$3.51.** No skill description needed changing.

## Command

```bash
claude plugin eval . --tag trigger --allow-tools "Bash(python3 *)" --ablation none --runs 1 -j 4 \
  --no-publish --max-cost-usd 5 --threshold 0.8 --trust-plugin
```

- `--ablation none`: under the default with-without ablation, `tool_used: Skill` graders are with-only and aren't
  scored.
- `--allow-tools "Bash(python3 *)"`: the slash cases run the CLI, and a case can't grant itself Bash.
- `--runs 1` overrides the case files' `runs: 3`, so every result is a single sample.

## Sandbox check (before the paid run)

The eval sandbox couldn't start on this host until bubblewrap had an AppArmor profile
(`apparmor_restrict_unprivileged_userns=1` on Ubuntu 24.04). After the owner loaded a profile scoped to
`/usr/bin/bwrap`, one `--case voice--slash` run scored 1.00 ($0.09). A second run with `--keep-temp` confirmed that
the skill's load-time `run.py profile` call read the checkout under the home directory: the reply mentioned "plugin
default" and "anchors: 0", text that only that command prints. The call ends in `|| true`, so a failed read would have
passed silently, which is why the check looked at the reply.

## Results

| Case | Kind | Grader(s) | Turns | Cost |
|---|---|---|---|---|
| adapt--natural | manual skill, plain request | does-not-fire | 7 | $0.22 |
| adapt--slash | slash | drafts | 3 | $0.17 |
| check--before-publishing | auto-trigger | fires | 4 | $0.13 |
| check--sounds-like-ai | auto-trigger | fires | 4 | $0.12 |
| check--their-or-there | near miss | does-not-fire | 1 | $0.08 |
| claims--natural | manual skill, plain request | does-not-fire | 2 | $0.11 |
| claims--slash | slash | saved-sources-line | 4 | $0.17 |
| copy-audit--natural | manual skill, plain request | does-not-fire | 1 | $0.09 |
| copy-audit--slash | slash | report-line | 2 | $0.13 |
| humanize--de-ai | auto-trigger | fires | 3 | $0.11 |
| humanize--less-chatgpt | auto-trigger | fires | 3 | $0.11 |
| humanize--more-formal | near miss | does-not-fire | 1 | $0.08 |
| plain-language--easier-for-non-technical | auto-trigger | fires | 3 | $0.11 |
| plain-language--fix-loop | near miss | does-not-fire (plain-language, write) | 1 | $0.08 |
| plain-language--parents-email | auto-trigger | fires | 4 | $0.14 |
| plain-language--translate | near miss | does-not-fire (plain-language) | 1 | $0.07 |
| plain-language--will-they-understand | auto-trigger | fires | 3 | $0.12 |
| reader-value--natural | manual skill, plain request | does-not-fire | 2 | $0.10 |
| reader-value--slash | slash | modes | 1 | $0.11 |
| register-check--natural | manual skill, plain request | does-not-fire | 1 | $0.08 |
| register-check--slash | slash | flags-only-line | 4 | $0.14 |
| voice--natural | manual skill, plain request | does-not-fire | 2 | $0.11 |
| voice--slash | slash | modes | 1 | $0.09 |
| write--blog-post-from-notes | auto-trigger | fires | 5 | $0.16 |
| write--email-from-brief | auto-trigger | fires | 7 | $0.24 |
| write--page-from-points | auto-trigger | fires | 10 | $0.27 |
| write--python-function | near miss | does-not-fire (plain-language, write) | 1 | $0.08 |
| write--summarise-changelog | near miss | does-not-fire (write) | 1 | $0.08 |

Wall clock 125 s at 4 runs in flight. No case reported an error.

## Limits

- One sample per case. A trigger that fires 4 times in 5 would pass here about as often as one that always fires;
  the case files' `runs: 3` is the setting to use when a description changes.
- The slash cases grade the reply's shape (a report line, a mode list), not the quality of the work. Output quality
  is covered by the Phase 2–4 end-to-end runs, not here.
- The plain-request cases for the six manual skills check only that they don't fire on their own, which is the
  intended behaviour (only write, check, humanize and plain-language auto-trigger).
