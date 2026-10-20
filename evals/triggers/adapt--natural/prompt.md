---
name: adapt--natural
description: Asking in plain words for a LinkedIn post must not start the manual-only adapt skill.
tags: [trigger, adapt]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Turn this paragraph into a LinkedIn post: "The Eastgate swimming pool reopens on 1 December after a four-month
rebuild. The new 25-metre lanes are wider and the change rooms are accessible."
