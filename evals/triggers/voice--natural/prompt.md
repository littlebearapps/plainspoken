---
name: voice--natural
description: Asking in plain words to capture a writing voice must not start the manual-only voice skill.
tags: [trigger, voice]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Capture my writing voice from these two paragraphs.

Paragraph one: I got up at five, made a terrible coffee and walked the dog down to the creek. It was cold. Nobody
else was out, which suited me fine.

Paragraph two: The meeting ran long, as it always does. I said what I thought, a bit too bluntly, and then bought
everyone a pie to make up for it.
