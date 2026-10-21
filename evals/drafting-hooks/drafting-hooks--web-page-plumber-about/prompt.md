---
name: drafting-hooks--web-page-plumber-about
description: Drafts a web page plumber about from notes that carry every fact, with the writing nudge and the drafting rule on.
tags: [drafting-hooks]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write the About page for my plumbing business's website.

> - Business: Doyle Plumbing, Wollongong.
> - Run by Kieran Doyle, licensed plumber for 15 years.
> - Two-person team: Kieran and apprentice Josh.
> - Mostly hot-water systems, blocked drains and small renovations.
> - Fixed quotes before any job starts.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
