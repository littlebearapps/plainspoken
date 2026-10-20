---
name: plain-language--parents-email
description: A request to rewrite an acronym-heavy email for parents should start plain-language.
tags: [trigger, plain-language]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Rewrite this school email so any parent gets it on one read: "Yr 5 EOY excursion forms are due to the front office
by Fri. PLC meeting Wed re: NAPLAN prep. P&C BBQ is on Sat, volunteers to the OSHC room."
