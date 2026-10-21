---
name: humanize--translate
description: Translating a paragraph is near the humanize trigger but outside it, so humanize does not fire.
tags: [trigger, humanize]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Translate this into French: "The library will be closed on Monday for the public holiday. Returns can go in the after-hours chute."
