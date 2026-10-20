---
name: claims--slash
description: The claims slash command on a draft that isn't there stops early and ends with the saved-sources line.
tags: [trigger, claims]
plugins: ["../../.."]
max_turns: 12
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:claims drafts/acme-plumbing-hot-water.md
