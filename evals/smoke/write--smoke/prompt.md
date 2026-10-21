---
name: write--smoke
description: Write from a saved brief drafts the email, runs the check and reports the status lines.
tags: [smoke, write]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, "Bash(python3 *)"]
---

/plainspoken:write brief.md --type email

brief.md doesn't exist yet. Save the text below to it first, exactly as written (without the > markers), then go on.

> # Brief: declining a meeting
>
> Audience: a colleague in another team who has invited you to a one-hour planning meeting next week.
>
> Format: a short email with a subject line, a greeting and a sign-off.
>
> Length: 80 to 120 words for the email body.
>
> Topic: politely declining a planning meeting because of a deadline that week.
>
> Ask them to send the notes afterwards, or propose a 15-minute call the following week. Keep the tone friendly and
> direct.
