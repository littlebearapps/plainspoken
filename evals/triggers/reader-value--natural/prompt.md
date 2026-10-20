---
name: reader-value--natural
description: Asking in plain words whether a planned post is worth a reader's time must not start the manual-only reader-value skill.
tags: [trigger, reader-value]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

I'm planning a post for Acme Plumbing called "Five signs your hot water system is on the way out". Is it actually
useful to a reader, or is it just there to get people to book a service?
