---
name: humanize--de-ai
description: A request to de-AI a paragraph should start the humanize skill.
tags: [trigger, humanize]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

De-AI this short paragraph: "Moreover, the committee underscored the pivotal role of volunteers. Additionally, it
highlighted the need to foster a robust sense of community across the suburb."
