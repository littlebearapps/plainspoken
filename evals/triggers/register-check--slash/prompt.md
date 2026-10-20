---
name: register-check--slash
description: The register-check slash command on a pasted follow-up reports the flags-only line.
tags: [trigger, register-check]
plugins: ["../../.."]
max_turns: 12
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:register-check --kind follow-up

Hi Priya, just following up on my note from last week about the garden quote. I know you're busy. If I don't hear
back by Thursday I'll assume you're not interested. Let me know either way. Thanks, Tom
