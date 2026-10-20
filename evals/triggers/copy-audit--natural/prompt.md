---
name: copy-audit--natural
description: Asking in plain words to audit homepage copy must not start the manual-only copy-audit skill.
tags: [trigger, copy-audit]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Can you audit the copy on my homepage hero?

Harbour Row Coffee
Fresh roasted beans, posted to your door every fortnight.
