---
name: rewrite--readme-intro--slash
description: Slash arm, through /plainspoken:humanize. A marketing-flavoured README intro rewritten to say plainly what the tool does, with no invented features.
tags: [rewrite-slash]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

/plainspoken:humanize This is the intro to my project's README. Can you rewrite it so it just says what the thing does?

> # Quillmark
>
> Quillmark is a cutting-edge, versatile Markdown linter — designed to elevate your documentation workflow. Built on a
> robust plugin architecture, it seamlessly integrates with your existing toolchain — and with over 40 built-in rules,
> it helps you maintain pristine, consistent docs across every project. Whether you're a solo developer or part of a
> large team — Quillmark empowers you to write with confidence. Get started in under 2 minutes — it's that easy!

Just send back the rewritten version, nothing else.
