---
name: check--smoke
description: A full check on a saved draft runs the lint and the four judges and gives merge's status line.
tags: [smoke, check]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

/plainspoken:check garden.md

garden.md doesn't exist yet. Save the text below to it first, exactly as written (without the > markers), then go on.

> In today's fast-paced world, our community garden stands as a testament to what neighbours can achieve.
> Moreover, the new raised beds will foster a vibrant sense of belonging. Working bees run on the first
> Saturday of each month from 9am, and plots cost $40 a year. Contact Priya Nair to join.
