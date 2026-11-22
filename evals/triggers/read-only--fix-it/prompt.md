---
name: read-only--fix-it
description: Asking to fix an email's tone is a rewrite, so the read-only entry must not start.
tags: [trigger, read-only]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Fix it: the tone of this email is off. Rewrite it so it's friendlier and send me the new version: "Per my last
email, kindly action the invoice ASAP."
