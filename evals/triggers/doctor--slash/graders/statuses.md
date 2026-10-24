---
type: regex
# The reply names python3 and leaves something unverified, and never says everything is fine (doctor's "never call
# an unverified item fine"; a regex can't see a single item called fine). `(?<![\s\S])` pins the match to the start
# of the reply, so the lookahead reads all of it.
pattern: '(?:^|\n)(?<![\s\S])(?![\s\S]*(?:\b(?:everything|all checks?|all items?|all of (?:it|them))\b[^\n]*?\b(?:fine|ok|okay|good|passed|clean|healthy)\b|\ball (?:good|clear|set)\b))[\s\S]*?\bpython3\b[\s\S]*\b(?:not checked|unverified|couldn.t (?:check|verify|confirm))\b'
flags: i
---
