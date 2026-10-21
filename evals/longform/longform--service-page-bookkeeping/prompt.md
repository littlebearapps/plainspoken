---
name: longform--service-page-bookkeeping
description: longform case longform--service-page-bookkeeping.
tags: [longform]
plugins: ["../../.."]
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write the service page (about 500 words) for my bookkeeping business's website.

> - Business: Ledger & Leaf, a sole-trader bookkeeping service in Hobart run by Anna Kowalski.
> - Services: BAS lodgement, payroll for up to 20 staff, Xero setup and clean-up.
> - Monthly packages start at $350; Xero clean-ups are quoted after a free 30-minute call.
> - Anna is a registered BAS agent with 11 years' experience.
> - Most clients are cafes, trades and small retailers.
> - She doesn't do tax returns; she refers those to a local accountant.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
