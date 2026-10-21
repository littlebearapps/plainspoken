---
name: drafting--x-thread-bin-changes
description: Drafts a x thread bin changes from notes that carry every fact.
tags: [drafting]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write a short thread (3 posts) for the council's account about the bin changes.

> - Darebin Council is moving green-waste collection from weekly to fortnightly from Monday 1 December.
> - Red and yellow bins don't change.
> - Residents can check their street's new day on the council website.
> - Households can request a second green bin for $45 a year.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
