---
name: rewrite--less-chatgpt--slash
description: Slash arm, through /plainspoken:humanize. An AI-sounding About blurb, rewritten so it doesn't read like ChatGPT, keeping its facts and adding none.
tags: [rewrite-slash]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

/plainspoken:humanize Can you make this sound less like ChatGPT wrote it? It's the About blurb for our community garden's website.

> Nestled in the heart of the suburb, the Elm Street Community Garden is a vibrant testament to what neighbours can
> achieve together. Since 2019, our 40 members have fostered a robust culture of sharing — from seed swaps to Saturday
> working bees — and every season brings new faces. Our 12 raised beds encompass a myriad of herbs, vegetables and
> native plants. Whether you're a seasoned grower or have never held a trowel, we're committed to providing a seamless,
> welcoming experience — because gardening is about more than plants — it's about community.

Just send back the rewritten version, nothing else.
