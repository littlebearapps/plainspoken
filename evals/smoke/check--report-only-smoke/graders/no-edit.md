---
type: regex
target: trace
# Report only: the run never edits garden.md after saving it.
pattern: '"name":"Edit","input":\{[^}]*garden\.md'
match: not_contains
---
