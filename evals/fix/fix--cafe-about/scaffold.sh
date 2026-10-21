#!/usr/bin/env bash
set -e
git init -q .
mkdir -p .plainspoken
printf '[nudge]\nmode = "on"\n\n[rule]\nenabled = true\n' > .plainspoken/config.toml
cat > about.md <<'DRAFT'
Nestled in the heart of Fremantle, Little Lune is more than just a cafe — it's a testament to the enduring power of family and tradition. Founded in 2019 by sisters Ana and Ruth Silva, our journey began with a shared passion for crafting unforgettable culinary experiences.

Every custard tart is meticulously handcrafted using our grandmother's treasured recipe, seamlessly blending heritage with innovation. Our coffee, sourced from a local roaster just two streets away, elevates every visit.

Whether you're a local or a visitor, we invite you to immerse yourself in the warm, welcoming atmosphere that makes Little Lune a beloved community hub. We're open 7am to 3pm, Tuesday to Sunday.
DRAFT
