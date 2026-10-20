---
name: adapt--slash
description: The adapt slash command on pasted text produces LinkedIn and Bluesky drafts without claiming to post.
tags: [trigger, adapt]
plugins: ["../../.."]
max_turns: 12
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:adapt "The Eastgate swimming pool reopens on 1 December after a four-month rebuild. The new 25-metre
lanes are wider, the change rooms are accessible, and entry stays at five dollars for under-16s." linkedin bluesky
