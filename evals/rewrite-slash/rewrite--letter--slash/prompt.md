---
name: rewrite--letter--slash
description: Slash arm, through /plainspoken:humanize. A formal letter to residents rewritten so it sounds like it came from a neighbour, keeping the dates, levels, contractor and contact.
tags: [rewrite-slash]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

/plainspoken:humanize Rewrite this letter to the residents in our building so it sounds like it came from a neighbour.

> Dear neighbours,
>
> We are writing to inform you of a pivotal upgrade to the Larkspur Court building — an upgrade that underscores our
> unwavering commitment to your comfort. Commencing Monday 3 March, contractors from Tallow Lifts will undertake
> comprehensive works on both lifts for approximately 10 working days. During this period — and we cannot stress
> this enough — residents on levels 4 to 8 are encouraged to utilise the stairwell — or contact the building
> manager, Priya Nand, for assistance. We appreciate your patience as we elevate your living experience.
>
> Kind regards,
> The Owners Committee

Just send back the rewritten version, nothing else.
