---
name: longform--newsletter-feature-library
description: longform case longform--newsletter-feature-library.
tags: [longform]
plugins: ["../../.."]
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Agent, Bash]
---

Write a feature for our council newsletter (about 450 words) on the library's new repair cafe.

> - Coburg Library started a monthly repair cafe in July in the community room.
> - Volunteers fix small appliances, clothes, bikes and toys for free; people pay nothing but are asked to stay and watch.
> - It runs on the second Saturday of each month, 10am to 1pm; no bookings, first come first served.
> - So far 212 items have come in and 151 were fixed; the most common were toasters, jeans and bike brakes.
> - Lead volunteer: Ray Petrakis, a retired electrician who worked 31 years for the railways.
> - Ray said: 'Half the toasters just need a crumb tray emptied. The other half need a new element and a bit of patience.'
> - Nothing with a petrol engine, and no microwaves, for safety.
> - A sewing volunteer, Mei Lin, fixed 40 pieces of clothing in October alone and can't keep up.
> - The library wants more volunteers who can sew; anyone interested can ask at the front desk.
> - Council's waste team estimates each fixed item keeps roughly a kilo out of landfill (an estimate, say so).

When it's ready, put the final text, and only that, between a line `<<<PIECE` and a line `PIECE>>>`.
