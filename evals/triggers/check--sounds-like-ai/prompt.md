---
name: check--sounds-like-ai
description: Asking whether text reads like AI wrote it should start the check skill.
tags: [trigger, check]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Does this read like AI wrote it? "Our bakery is a vibrant tapestry of flavours, offering a seamless and unforgettable
experience that truly elevates every morning."
