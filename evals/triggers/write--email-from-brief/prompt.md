---
name: write--email-from-brief
description: A request to draft an email from a brief should start the write skill.
tags: [trigger, write]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Draft an email to the choir members telling them rehearsals move from Tuesday to Wednesday from 4 March. Same hall,
same 7 pm start. Keep it short and friendly.
