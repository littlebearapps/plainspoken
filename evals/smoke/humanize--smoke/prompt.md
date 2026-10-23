---
name: humanize--smoke
description: Humanize on pasted text returns a rewrite without the hard-ban words and keeps the facts.
tags: [smoke, humanize]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

/plainspoken:humanize Just send back the rewritten version, nothing else.

> In today's fast-paced world, our community garden stands as a testament to what neighbours can achieve.
> Moreover, the new raised beds will foster a vibrant sense of belonging. Working bees run on the first
> Saturday of each month from 9am, and plots cost $40 a year. Contact Priya Nair to join.
