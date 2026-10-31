---
type: regex
target: trace
# Fails a run that sends a run.py check call's output to /dev/null (#162): the lint is read in full, never thrown away. A claims call's 2>/dev/null doesn't count.
pattern: '(?:run\.py|\$[A-Za-z_]+)(?:\\"|\x27)?[ ]+check (?:[^;&|\n"\\]|\\.)*? (?:&|1)?>[ ]*/dev/null'
match: not_contains
---
