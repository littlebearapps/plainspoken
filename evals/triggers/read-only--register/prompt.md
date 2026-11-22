---
name: read-only--register
description: Asking to check a draft's register, with no edit asked for, starts the read-only entry (#245).
tags: [trigger, read-only]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Check this draft's register before it goes out, and don't change anything: "Hi Priya, just following up on
my note from last week about the garden quote. If I don't hear back by Thursday I'll assume you're not
interested. Thanks, Tom"
