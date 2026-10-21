---
name: register-check--smoke
description: A register check of a pasted email gives the flags and the flags-only line.
tags: [smoke, register-check]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, "Bash(python3 *)"]
---

/plainspoken:register-check email

> Hi Sam, per my last email, kindly action the invoice ASAP. Thanks in advance!
