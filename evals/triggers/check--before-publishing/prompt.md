---
name: check--before-publishing
description: Asking for the AI-writing check before publishing should start the check skill.
tags: [trigger, check]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Before I publish this paragraph, run your AI-writing check on it: "The new tram timetable starts on Monday. Most
routes run every ten minutes at peak, and the last service leaves the depot at 11.40 pm."
