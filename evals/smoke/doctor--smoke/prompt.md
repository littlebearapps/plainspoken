---
name: doctor--smoke
description: Doctor in Claude Code runs the checks, reports the Bash permission line and changes nothing.
tags: [smoke, doctor]
plugins: ["../../.."]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
# No first-call grader (#58). doctor reads no profile; its first step is doctor --host.
---

/plainspoken:doctor claude-code
