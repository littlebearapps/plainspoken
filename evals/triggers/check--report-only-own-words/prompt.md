---
name: check--report-only-own-words
description: Asking whether text sounds like AI while keeping the writer's words should start check, never humanize.
tags: [trigger, check]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

My manager wrote this herself and wants it kept word for word. Tell me if any of it sounds like AI, but don't edit
it: "Moreover, our team remains committed to fostering a robust culture of care across every one of our clinics."
