---
name: reader-value--smoke
description: A reader-value outline for a saved draft gives the outline status line.
tags: [smoke, reader-value]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, "Bash(python3 *)"]
---

/plainspoken:reader-value outline garden.md

garden.md doesn't exist yet. Save the text below to it first, exactly as written (without the > markers), then go on.

> In today's fast-paced world, our community garden stands as a testament to what neighbours can achieve.
> Moreover, the new raised beds will foster a vibrant sense of belonging. Working bees run on the first
> Saturday of each month from 9am, and plots cost $40 a year. Contact Priya Nair to join.
