---
name: humanize--more-formal
description: Changing register to more formal is near the humanize trigger but outside it, so humanize does not fire.
tags: [trigger, humanize]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Make this casual email more formal for my bank manager: "Hey Dana, just checking if the loan thing is sorted yet?
Need to know by Friday if poss. Cheers, Sam"
