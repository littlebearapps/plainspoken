---
name: humanize--sounds-like-person
description: A plain request to make text sound like a person wrote it should start the humanize skill.
tags: [trigger, humanize]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Can you rewrite this so it sounds like a person wrote it? "We are thrilled to announce that our community garden will be reopening its gates this spring, offering residents a vibrant space to cultivate connections."
