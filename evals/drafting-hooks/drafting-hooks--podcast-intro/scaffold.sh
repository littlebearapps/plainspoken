#!/usr/bin/env bash
set -e
git init -q .
mkdir -p .plainspoken
printf '[nudge]\nmode = "on"\n\n[rule]\nenabled = true\n' > .plainspoken/config.toml
