---
name: rewrite--linkedin-post--slash
description: Slash arm, through /plainspoken:humanize. A LinkedIn post full of AI tells, tidied into plain words with the post's facts and nothing new.
tags: [rewrite-slash]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

/plainspoken:humanize Tidy this LinkedIn post before I put it up. It reads like a bot wrote it.

> Thrilled to share a pivotal milestone! 🚀 After 18 months of meticulous work, our team at Harbourline Logistics has
> launched a groundbreaking route-planning tool that will revolutionise how small couriers operate. This isn't just
> software — it's a game-changer. It empowers drivers to streamline their days, and early pilots cut fuel use by 14%.
> I'm incredibly grateful to everyone who made this possible — you know who you are. The journey is just beginning!

Just send back the rewritten version, nothing else.
