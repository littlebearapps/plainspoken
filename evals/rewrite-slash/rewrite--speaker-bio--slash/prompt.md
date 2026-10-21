---
name: rewrite--speaker-bio--slash
description: Slash arm, through /plainspoken:humanize. An inflated speaker bio rewritten plainly, keeping her name, town and years.
tags: [rewrite-slash]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

/plainspoken:humanize Rewrite this speaker bio so it sounds like a real person and not a LinkedIn summary.

> Dr Mei Tan is a renowned, visionary veterinarian whose groundbreaking work has transformed animal care in 
> Launceston — and beyond. With over 22 years of invaluable experience, she leverages a holistic approach to 
> empower small clinics. Her talk will delve into the intricate interplay between rural farm visits and urban 
> practice — a must-see session. When she isn't working, Mei cultivates a thriving garden — and her beloved 
> beehives — of course.

Just send back the rewritten version, nothing else.
