---
name: drafting-hooks--linkedin-new-hire
description: Drafts a linkedin new hire from notes that carry every fact, with the writing nudge and the drafting rule on.
tags: [drafting-hooks]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Draft a LinkedIn post announcing our new hire.

> - Firm: Hargreaves & Lin, a 6-person bookkeeping practice in Geelong.
> - New hire: Priya Desai, starting Monday 2 November as a senior bookkeeper.
> - Priya spent 8 years doing payroll for hospitality businesses.
> - She'll look after our cafe and restaurant clients.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
