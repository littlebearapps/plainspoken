---
name: register-check--natural
description: Asking in plain words to check an email's tone must not start the manual-only register-check skill.
tags: [trigger, register-check]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Check the tone of this email before I send it: "Hi Priya, just following up on my note from last week about the
garden quote. Let me know either way. Thanks, Tom"
