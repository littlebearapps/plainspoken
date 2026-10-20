---
name: kaizen--slash
description: The kaizen slash command with no argument lists its modes and runs nothing else.
tags: [trigger, kaizen]
plugins: ["../../.."]
max_turns: 12
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:kaizen
