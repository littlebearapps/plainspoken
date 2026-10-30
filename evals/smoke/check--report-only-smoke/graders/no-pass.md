---
type: regex
# The draft has BLOCK-level tells and nothing gets fixed, so the report must never call it a pass.
pattern: '\bPASS\b[^\n]{0,40}coverage\s+[0-9]+/[0-9]+'
flags: i
match: not_contains
---
