---
name: check--report-only
description: Asking for the AI-writing check without edits should start check (its report-only route), never humanize.
tags: [trigger, check]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Check this but don't change anything: "Our library is a vibrant hub of learning, offering a seamless experience that
truly empowers every reader in the community."
