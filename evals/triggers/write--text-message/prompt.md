---
name: write--text-message
description: A request to draft a text message should start the write skill.
tags: [trigger, write]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Write a text message to my neighbour Tom: the fence repair is booked for Saturday morning and the builder will need the side gate open.
