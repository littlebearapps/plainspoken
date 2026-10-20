---
name: write--blog-post-from-notes
description: A plain request to write a post from notes should start the write skill.
tags: [trigger, write]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Here are my notes from running a repair café last Saturday: 23 people came, we fixed 14 of 19 items, two toasters
were beyond saving, and the volunteers want a monthly slot. Write a 400-word post for the café's website about how
it went.
