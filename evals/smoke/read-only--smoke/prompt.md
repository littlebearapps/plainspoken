---
name: read-only--smoke
description: A read-only register check of a pasted email gives the flags, the read-only line and the flags-only line, and writes no file.
tags: [smoke, read-only]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

/plainspoken:read-only register-check email

> Hi Sam, per my last email, kindly action the invoice ASAP. Thanks in advance!
