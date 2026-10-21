---
name: write--sql-query
description: Writing a SQL query is code, not prose, so the write skill does not fire.
tags: [trigger, write]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Write a SQL query that lists every customer who ordered more than twice last month.
