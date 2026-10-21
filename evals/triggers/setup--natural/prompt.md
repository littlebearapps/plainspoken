---
name: setup--natural
description: Asking in plain words about the nudge must not start the manual-only setup skill.
tags: [trigger, setup]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Can you explain what plainspoken's writing nudge does and whether I'd want it?
