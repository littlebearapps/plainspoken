---
name: fix--client-email
description: fix case fix--client-email.
tags: [fix]
plugins: ["../../.."]
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Can you go through email.md and fix anything that sounds like AI wrote it? Keep every fact. Save the fixed version to email.md. When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
