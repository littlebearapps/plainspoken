---
name: setup--smoke
description: Setup with the person's choices given up front turns the nudge and rule on and shows the status.
tags: [smoke, setup]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
# No first-call grader (#58). setup reads no profile; its first step is setup --status.
---

/plainspoken:setup claude-code

I've decided already: writing nudge on, drafting rule on, lint after edits on, project scope. Apply it without asking again.
