---
name: voice--slash
description: The voice slash command with no argument lists its modes.
tags: [trigger, voice]
plugins: ["../../.."]
max_turns: 12
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:voice
