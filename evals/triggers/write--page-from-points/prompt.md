---
name: write--page-from-points
description: A request to draft a web page from a list of facts should start the write skill.
tags: [trigger, write]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Draft the "About the market" page for our farmers' market from these facts: it runs every Sunday from 8 am to 1 pm,
there are 32 stalls, it started in 2011 in the church car park, all produce comes from within 100 km, and parking
is free.
