---
name: longform--newsletter-feature-library
description: longform case longform--newsletter-feature-library.
tags: [longform]
plugins: ["../../.."]
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write a feature for our council newsletter (about 500 words) on the library's new repair cafe.

> - Coburg Library started a monthly repair cafe in July.
> - Volunteers fix small appliances, clothes and bikes for free.
> - It runs on the second Saturday of each month, 10am to 1pm.
> - So far 212 items have been brought in and 151 fixed.
> - Lead volunteer: Ray Petrakis, a retired electrician.
> - People can't bring anything with a petrol engine.
> - The library wants more volunteers who can sew.

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
