---
name: reader-value--slash
description: The reader-value slash command with no argument asks which of its two modes to run.
tags: [trigger, reader-value]
plugins: ["../../.."]
max_turns: 12
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:reader-value
