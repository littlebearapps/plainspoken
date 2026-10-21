---
name: fix--council-update
description: fix case fix--council-update.
tags: [fix]
plugins: ["../../.."]
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Can you go through council-update.md and fix anything that sounds like AI wrote it? Keep every fact. Save the fixed version to council-update.md. When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
