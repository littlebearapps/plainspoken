---
name: write--summarise-changelog
description: Summarising a changelog is near the write trigger but outside it, so write does not fire.
tags: [trigger, write]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Summarise this changelog so I know whether to upgrade:

v2.4.0: Adds a dark theme. Fixes a crash when the sync folder is empty.
v2.4.1: Drops support for the old export format.
