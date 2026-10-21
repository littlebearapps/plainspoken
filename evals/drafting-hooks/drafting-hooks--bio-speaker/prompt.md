---
name: drafting-hooks--bio-speaker
description: Drafts a bio speaker from notes that carry every fact, with the writing nudge and the drafting rule on.
tags: [drafting-hooks]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write a short speaker bio for a conference program, about 100 words.

> - Speaker: Dr Mei Tan.
> - Runs a vet clinic in Launceston.
> - Has worked as a vet for 22 years.
> - Talk: what small clinics can learn from rural farm visits.
> - Keeps bees and grows too many tomatoes.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
