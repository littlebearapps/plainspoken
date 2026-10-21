---
name: setup--slash
description: The setup slash command shows what is on now and recommends the pieces, without changing anything unasked.
tags: [trigger, setup]
plugins: ["../../.."]
max_turns: 10
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:setup
