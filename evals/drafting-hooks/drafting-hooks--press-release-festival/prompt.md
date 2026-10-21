---
name: drafting-hooks--press-release-festival
description: Drafts a press release festival from notes that carry every fact, with the writing nudge and the drafting rule on.
tags: [drafting-hooks]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write a press release announcing our festival.

> - Event: Riverlight Festival, Echuca.
> - Dates: Friday 6 to Sunday 8 March.
> - 40 local food and wine stalls, and live music each night.
> - Entry is free; the lantern parade starts at 7pm Saturday.
> - Media contact: Dee Collins, festival coordinator.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
