---
name: rewrite--client-email--slash
description: Slash arm, through /plainspoken:humanize. A stiff, AI-sounding email to a new client rewritten so a person could have sent it, with its price, what the fee leaves out, the approval promise and the cancel condition kept.
tags: [rewrite-slash]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

/plainspoken:humanize Can you rewrite this email to a new client so it sounds like a person wrote it?

> Hi Priya,
>
> Thank you so much for reaching out — it's truly a pleasure to be working with Greenway Plumbing! I'm thrilled to
> confirm that your first website review is completely free and will take approximately two weeks. Following that,
> my ongoing support is $180 a month — a seamless way to keep everything running smoothly. Please note that hosting
> is billed separately and isn't included in that fee. Rest assured, I won't publish any changes without your
> approval — your vision always comes first. If you cancel before the 1st of the month, you won't be charged for
> that month. I look forward to a robust and invaluable partnership — let's elevate your online presence together!
>
> Warm regards,
> Sam

Just send back the rewritten version, nothing else.
