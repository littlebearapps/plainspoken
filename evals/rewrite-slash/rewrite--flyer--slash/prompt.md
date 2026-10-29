---
name: rewrite--flyer--slash
description: Slash arm, through /plainspoken:humanize. A school fair flyer full of hype rewritten so a parent would read it at a glance, keeping the date, times, prices and place.
tags: [rewrite-slash]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

/plainspoken:humanize Can you rewrite this flyer for our school fair so it's quick to read and doesn't sound like an ad?

> Join us for an unforgettable day of fun at the Kestrel Hill Spring Fair — a vibrant celebration of everything our
> community has to offer! On Saturday 14 September, from 9am to 3pm, Kestrel Hill Primary School will transform into
> a bustling hub of 30 stalls, live music and delicious food — truly a must-visit event. Entry is just $5 for adults
> — and kids under 12 go free. Don't miss this groundbreaking opportunity to connect with your neighbours — see you
> there!

Just send back the rewritten version, nothing else.
