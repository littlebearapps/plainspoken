---
name: adapt--smoke
description: Adapting a saved post for two platforms gives drafts for both and posts nothing.
tags: [smoke, adapt]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

/plainspoken:adapt garden.md linkedin bluesky

garden.md doesn't exist yet. Save the text below to it first, exactly as written (without the > markers), then go on.

> In today's fast-paced world, our community garden stands as a testament to what neighbours can achieve.
> Moreover, the new raised beds will foster a vibrant sense of belonging. Working bees run on the first
> Saturday of each month from 9am, and plots cost $40 a year. Contact Priya Nair to join.
