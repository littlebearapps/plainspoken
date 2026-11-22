---
name: read-only--build-profile
description: Asking to build and save a voice profile writes a file, so the read-only entry must not start.
tags: [trigger, read-only]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Build me a voice profile from these two paragraphs and save it for next time.

Paragraph one: I got up at five, made a terrible coffee and walked the dog down to the creek. It was cold.

Paragraph two: The meeting ran long, as it always does. I said what I thought, a bit too bluntly.
