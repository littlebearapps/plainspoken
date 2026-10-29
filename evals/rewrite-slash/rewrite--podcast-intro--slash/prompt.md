---
name: rewrite--podcast-intro--slash
description: Slash arm, through /plainspoken:humanize. An over-produced podcast opening rewritten so the host sounds like she's talking, keeping the names, the episode and the numbers.
tags: [rewrite-slash]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

/plainspoken:humanize Rewrite the opening of my podcast so it sounds like I'm actually talking to someone.

> Welcome to Back Paddock Talk, the podcast that delves into the vibrant world of small-scale farming. I'm your
> host, Tessa Marlow, and in today's episode — episode 42 — we unpack a pivotal question: how can a family farm
> leverage its 60 acres to stay afloat? Joining me is agronomist Dev Okafor — a true beacon of practical wisdom —
> who has spent 15 years helping growers through tough seasons. Buckle up, because this conversation is a
> game-changer.

Just send back the rewritten version, nothing else.
