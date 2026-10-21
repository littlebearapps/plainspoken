#!/usr/bin/env bash
set -e
git init -q .
mkdir -p .plainspoken
printf '[nudge]\nmode = "on"\n\n[rule]\nenabled = true\n' > .plainspoken/config.toml
cat > newsletter.md <<'DRAFT'
As we navigate the final weeks of the season, it's worth taking a moment to reflect on the remarkable journey we've shared. The Northside Harriers have truly embodied the spirit of camaraderie, with our 85 members logging an impressive 3,200 kilometres since February.

This achievement is a testament to the dedication, resilience and unwavering commitment that define our club. Moreover, it underscores the pivotal role that community plays in fostering a culture of excellence.

The upcoming 10 km fun run on 22 June will serve as a fitting celebration of our collective accomplishments. We look forward to seeing you there — let's make it an unforgettable day!
DRAFT
