---
name: rewrite--video-script
description: A puffed-up video script rewritten so it sounds spoken by a real cafe owner, keeping the names and hours.
tags: [rewrite]
plugins: ["../../.."]
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
---

Rewrite this script for our cafe video so it sounds like a person talking, not an ad.

> Nestled in the heart of Fremantle, Little Lune is more than a cafe — it's a vibrant community hub. Founded by 
> sisters Ana and Ruth Silva, our journey is a testament to passion and family. Every custard tart is crafted 
> with meticulous care — a seamless blend of tradition and innovation — and love. We open at 7am — come and 
> experience the magic for yourself.

Just send back the rewritten version, nothing else.
