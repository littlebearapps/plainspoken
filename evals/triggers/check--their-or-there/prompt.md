---
name: check--their-or-there
description: A grammar question is near the check trigger but outside it, so check does not fire.
tags: [trigger, check]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Is "their" or "there" right in this sentence? "The kids left ___ bags by the gate."
