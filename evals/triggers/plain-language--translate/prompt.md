---
name: plain-language--translate
description: Translation is near the plain-language trigger but outside it, so plain-language does not fire.
tags: [trigger, plain-language]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Translate this one-line library notice into French: "The library will close at 5 pm on Friday for stocktake."
