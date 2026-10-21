---
name: kaizen--smoke
description: Kaizen review on a fresh project reports the mode and the engine's status.
tags: [smoke, kaizen]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, "Bash(python3 *)"]
---

/plainspoken:kaizen review
