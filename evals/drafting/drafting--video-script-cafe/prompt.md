---
name: drafting--video-script-cafe
description: Drafts a video script cafe from notes that carry every fact.
tags: [drafting]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write a 60-second video script for a walk-through of our cafe for social media.

> - Cafe: Little Lune, Fremantle.
> - Opened in 2019 by sisters Ana and Ruth Silva.
> - Coffee roasted by a roaster two streets away.
> - Known for the Portuguese custard tarts their grandmother taught them.
> - Open 7am to 3pm, closed Mondays.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
