---
name: kaizen--natural
description: Asking in plain words to stop a rule from flagging things must not start the manual-only kaizen skill.
tags: [trigger, kaizen]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

The writing check keeps flagging short sentences in my FAQ answers, and I think they're fine there. Can you tune the
rules so it stops doing that?
