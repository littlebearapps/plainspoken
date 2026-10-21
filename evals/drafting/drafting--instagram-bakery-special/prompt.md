---
name: drafting--instagram-bakery-special
description: Drafts a instagram bakery special from notes that carry every fact.
tags: [drafting]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write an Instagram caption for this week's special at our bakery.

> - Bakery: Crumb & Co, Bendigo.
> - Special: pumpkin and feta scrolls, $6 each.
> - Only on Thursday and Friday this week.
> - Usually sold out by 11am.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
