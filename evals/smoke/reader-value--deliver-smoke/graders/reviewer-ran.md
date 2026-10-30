---
type: regex
target: trace
# Passes when deliver was recorded with the isolated reviewer's label (step 3), not a self-check.
pattern: 'reader-value(?:\\"|\x27)?[ ]+deliver[ ]+(?:[^"\\]|\\[\s\S])*--reviewer[ ]+delivery-checker'
---
