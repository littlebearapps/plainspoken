---
name: drafting--newsletter-school
description: Drafts a newsletter school from notes that carry every fact.
tags: [drafting]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write the principal's message for this term's school newsletter.

> - School: Westgarth Primary.
> - Principal: Helen Marsh.
> - The new library opens on Monday 10 November.
> - Parents raised $18,000 for it at the autumn fete.
> - Working bee on Saturday 15 November to move the books.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
