---
name: write--python-function
description: A request for code is near the write trigger but outside it, so neither drafting skill fires.
tags: [trigger, write]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Write a Python function that parses ISO 8601 dates and returns a datetime. Just the code, please.
