#!/usr/bin/env bash
set -e
git init -q .
mkdir -p .plainspoken
printf '[nudge]\nmode = "on"\n\n[rule]\nenabled = true\n' > .plainspoken/config.toml
cat > about.md <<'DRAFT'
At Doyle Plumbing, we pride ourselves on delivering exceptional, comprehensive plumbing solutions tailored to the unique needs of every Wollongong household. With over 15 years of industry expertise, founder Kieran Doyle has cultivated a reputation for reliability, integrity and excellence.

Our dedicated two-person team — Kieran and apprentice Josh — specialises in hot-water systems, blocked drains and small renovations. We leverage cutting-edge techniques to ensure seamless outcomes, every time.

Transparency is at the core of everything we do, which is why we provide fixed quotes before any job begins. Experience the Doyle difference today!
DRAFT
