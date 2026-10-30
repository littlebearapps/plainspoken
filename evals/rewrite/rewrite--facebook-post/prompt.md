---
name: rewrite--facebook-post
description: A bakery's Facebook post full of AI tells rewritten in the owner's own voice, keeping the shop, the suburb, the day and the hours.
tags: [rewrite]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Make this Facebook post for my bakery sound like me, not a marketing bot.

> Big news, foodies! 🎉 Bramblewick Bakery is thrilled to announce that our Elmstead store is expanding its hours —
> we're now open until 6pm on Thursdays! This is a game-changer for busy families, and we're committed to providing
> a seamless experience every time. Pop in, grab a loaf from our 8 signature sourdoughs and elevate your afternoon —
> your taste buds will thank you.

Just send back the rewritten version, nothing else.
