---
name: rewrite--sms-running-late
description: A stiff, formal text message rewritten the way a person would text it, keeping the time and the place.
tags: [rewrite]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Can you rewrite this text so it sounds like I actually sent it?

> Hi there! I hope this message finds you well — I wanted to reach out to let you know that I will unfortunately 
> be running approximately 15 minutes late to our coffee at Brunetti. Rest assured — I remain fully committed to 
> our meeting, and I'll leverage the extra time to finalise the crucial, robust and seamless handover notes for 
> Thursday.

Just send back the rewritten version, nothing else.
