---
name: copy-audit--slash
description: The copy-audit slash command on pasted text reports a Copy audit.
tags: [trigger, copy-audit]
plugins: ["../../.."]
max_turns: 12
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, "Bash(python3 *)"]
---

/plainspoken:copy-audit audit this hero text instead of a file:

Harbour Row Coffee
Fresh roasted beans, posted to your door every fortnight.
