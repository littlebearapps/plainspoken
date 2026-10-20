---
name: plain-language--fix-loop
description: Fixing a code bug is outside both drafting skills, so neither fires.
tags: [trigger, plain-language]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

This loop skips the last item. Fix the off-by-one error:

for i in range(len(items) - 1):
    print(items[i])
