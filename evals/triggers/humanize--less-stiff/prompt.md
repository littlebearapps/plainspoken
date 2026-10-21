---
name: humanize--less-stiff
description: Asking for a stiff paragraph to be less stiff, with only the rewrite wanted back, should start the humanize skill.
tags: [trigger, humanize]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Here's the opening of our newsletter. Make it less stiff. Just send back the rewritten version, nothing else.

> In today's fast-paced world, staying informed is more important than ever. This month, we are excited to share a range of updates that underscore our commitment to the club.
