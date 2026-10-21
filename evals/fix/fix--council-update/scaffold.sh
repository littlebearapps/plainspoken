#!/usr/bin/env bash
set -e
git init -q .
mkdir -p .plainspoken
printf '[nudge]\nmode = "on"\n\n[rule]\nenabled = true\n' > .plainspoken/config.toml
cat > council-update.md <<'DRAFT'
In today's rapidly evolving landscape, Darebin Council remains steadfastly committed to fostering a vibrant and sustainable community. We are thrilled to announce a pivotal change to green-waste collection, which will move from weekly to fortnightly from Tuesday 1 December. This transformative initiative underscores our dedication to environmental stewardship.

Residents can seamlessly check their street's new collection day on the council website. Furthermore, households seeking additional capacity can request a second green bin for just $45 a year — an invaluable option for keen gardeners.

Red and yellow bins will remain unchanged. Together, we can unlock a greener future for Darebin — one bin at a time.
DRAFT
