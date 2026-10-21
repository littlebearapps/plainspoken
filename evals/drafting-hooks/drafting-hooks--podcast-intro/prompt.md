---
name: drafting-hooks--podcast-intro
description: Drafts a podcast intro from notes that carry every fact, with the writing nudge and the drafting rule on.
tags: [drafting-hooks]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write the spoken intro for episode 12 of my podcast.

> - Podcast: Small Shop, Big Week, about running a small retail business in regional Australia.
> - Host: me, Tom Brennan.
> - Guest: Lisa Ng, who runs a hardware store in Mudgee.
> - Topic: how she survived the store's first winter after a flood.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
