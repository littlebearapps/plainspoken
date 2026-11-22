---
name: read-only--voice
description: Asking whether a draft sounds like the writer's voice profile, without edits, starts the read-only entry.
tags: [trigger, read-only]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Does this paragraph sound like me? Check it against my voice profile but don't edit it: "We are delighted to
announce an exciting new chapter for our community garden, as we continue our journey of growth."
