#!/usr/bin/env bash
set -e
git init -q .
mkdir -p .plainspoken
printf '[nudge]\nmode = "on"\n\n[rule]\nenabled = true\n' > .plainspoken/config.toml
cat > email.md <<'DRAFT'
Hi Priya,

Thank you so much for reaching out — it's truly a pleasure to be working with Greenway Plumbing! I'm thrilled to confirm that your first website review is completely free and will take approximately two weeks. Following that, my ongoing support is $180 a month — a seamless way to keep everything running smoothly. Please note that hosting is billed separately and isn't included in that fee. Rest assured, I won't publish any changes without your approval — your vision always comes first. If you cancel before the 1st of the month, you won't be charged for that month. I look forward to a robust and invaluable partnership — let's elevate your online presence together!

Warm regards,
Sam
DRAFT
