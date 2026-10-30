---
name: reader-value--deliver-smoke
description: Deliver mode on a saved draft and contract chains its CLI calls, runs the isolated reviewer and gives the deliver status line.
tags: [smoke, reader-value]
plugins: ["../../.."]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

/plainspoken:reader-value deliver drain.md

This folder is the project: save an empty file at `.plainspoken/config.toml` here first.

drain.md doesn't exist yet. Save the text below to it first, exactly as written (without the > markers).

> # Is a slow kitchen drain a DIY job?
>
> Most slow kitchen drains are a blocked trap, and you can clear one in about 30 minutes with a bucket and a sink
> plunger. Start under the kitchen sink: put the bucket under the trap, then remove the sink strainer and trap cap.
> Pull out what's in there and put the cap back. Fill the sink and pull the plug. If a full sink empties in under a
> minute, you're done.
>
> If it's still slow, plunge it ten times with the overflow covered and try again. Stop and call a licensed plumber
> if water backs up into another fixture, such as the shower or the laundry trough: that means the blockage is
> further down the line, past anything a plunger reaches.

Then save the text below at `.plainspoken/reader-value/drain.reader-value.toml`, exactly as written (without the >
markers), and go on.

> schema_version = 1
> type = "task"
> primary_reader = "A homeowner with a slow-draining kitchen sink"
> problem = "Can't tell whether a slow drain is a do-it-yourself job or needs a plumber"
> promised_outcome = "A cleared drain, or a clear sign that it's a job for a licensed plumber"
> effort = "about 30 minutes"
> prerequisites = ["a bucket", "a sink plunger"]
> success_signal = "A full sink empties in under a minute"
> stop_condition = "Stop and call a licensed plumber if water backs up into another fixture"
> original_value = "A plain triage: trap first, then plunger, then the sign that it's past DIY"
> cta_excluded_confirmed = true
>
> [first_action]
> verb = "remove"
> object = "the sink strainer and trap cap"
> location = "under the kitchen sink"
