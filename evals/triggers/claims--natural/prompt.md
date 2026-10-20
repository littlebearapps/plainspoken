---
name: claims--natural
description: Asking in plain words to fact-check a paragraph must not start the manual-only claims skill.
tags: [trigger, claims]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Can you fact-check the numbers in this paragraph before I put it on our website? "Acme Plumbing has fitted more than
1,200 hot water systems since 2015, and a heat pump uses about a third of the power of an electric storage unit."
