---
name: drafting--pamphlet-pool-safety
description: Drafts a pamphlet pool safety from notes that carry every fact.
tags: [drafting]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write the text for a one-page pamphlet about pool safety for parents.

> - From: Ballarat Aquatic Centre.
> - Children under 10 must be within arm's reach of an adult in the water.
> - Lifeguards are on duty 6am to 8pm.
> - Free 30-minute water-safety sessions for parents run on Sundays at 9am.
> - Bookings at the front desk.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
