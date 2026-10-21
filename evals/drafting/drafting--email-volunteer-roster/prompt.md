---
name: drafting--email-volunteer-roster
description: Drafts a email volunteer roster from notes that carry every fact.
tags: [drafting]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Can you write an email to our pantry volunteers about the roster change?

> - The Northcote Community Pantry is moving its Saturday shift from 9am to 10am, starting Saturday 7 November.
> - Reason: the hall's cleaners now come at 9am.
> - Shift length stays 3 hours.
> - Anyone who can't make the new time should reply to Maria Lopez by Friday 30 October.
> - Sign off from Maria.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
