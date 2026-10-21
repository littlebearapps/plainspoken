---
name: humanize--reads-like-a-bot
description: Saying a draft reads like a bot wrote it should start the humanize skill.
tags: [trigger, humanize]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

This reads like a bot wrote it, can you fix it? "Furthermore, our seamless onboarding process empowers new members to navigate the platform with ease."
