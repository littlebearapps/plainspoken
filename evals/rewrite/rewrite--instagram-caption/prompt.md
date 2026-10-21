---
name: rewrite--instagram-caption
description: An AI-sounding bakery caption rewritten in a shop owner's own voice, keeping the price and the days.
tags: [rewrite]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Rewrite this Instagram caption for my bakery so it doesn't sound like a robot wrote it.

> Elevate your weekend with our vibrant new sourdough range — a true testament to the art of baking! Crafted 
> with meticulous care at Crumb & Co in Bendigo, each loaf is a game-changer for your breakfast table. Available 
> Saturday and Sunday only — just $9 a loaf. Don't miss out!

Just send back the rewritten version, nothing else.
