---
name: drafting--sms-dentist-reschedule
description: Drafts a sms dentist reschedule from notes that carry every fact.
tags: [drafting]
plugins: ["../../.."]
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write a text message I can send to my dentist's office to move my appointment.

> - My name is Sam Okafor.
> - Current appointment: Tuesday 4 November at 2:30pm.
> - I need to move it because of a work trip.
> - Any weekday morning the following week works.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
