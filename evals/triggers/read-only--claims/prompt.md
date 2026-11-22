---
name: read-only--claims
description: Asking for a report on an article's claim ledger, with nothing to change, starts the read-only entry.
tags: [trigger, read-only]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Run the claims check on drafts/hot-water.md against the ledger it already has and tell me what's still open.
Report only: don't change the article or the ledger.
