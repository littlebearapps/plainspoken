---
name: doctor--natural
description: Asking in plain words what plainspoken needs on a machine must not start the manual-only doctor skill.
tags: [trigger, doctor]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

What does plainspoken need installed on my computer to work properly?
