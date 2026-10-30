---
name: check--report-only-smoke
description: A report-only check runs the lint and the judges, leaves the draft's bytes alone and never calls a failing draft a pass.
tags: [smoke, check]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

/plainspoken:check garden.md, report only: don't change anything, the words have to stay mine. Just tell me what you
find.

This folder is the project: save an empty file at `.plainspoken/config.toml` here first.

garden.md doesn't exist yet. Save the text below to it first, exactly as written (without the > markers), then run
`sha256sum garden.md` and go on.

> In today's fast-paced world, our community garden stands as a testament to what neighbours can achieve.
> Moreover, the new raised beds will foster a vibrant sense of belonging. Working bees run on the first
> Saturday of each month from 9am, and plots cost $40 a year. Contact Priya Nair to join.
