---
name: doctor--slash
description: The doctor slash command runs the host checks and reports each line's status, changing nothing.
tags: [trigger, doctor]
plugins: ["../../.."]
max_turns: 10
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:doctor
