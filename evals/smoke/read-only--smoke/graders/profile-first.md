---
type: regex
target: trace
# Passes when the run's first run.py call is run.py profile (#58). Built by evaltrace.grader_pattern; eval first-call shows what ran first.
pattern: '^(?:(?!"name":"Bash","input":\{(?:"[a-z_]+":(?:"(?:[^"\\]|\\[\s\S])*"|[^,{}"]*),)*"command":"(?:(?!run\.py(?:\\"|\x27)?[ ]+[a-z-])(?:[^"\\]|\\[\s\S]))*run\.py(?:\\"|\x27)?[ ]+[a-z-])[\s\S])*"name":"Bash","input":\{(?:"[a-z_]+":(?:"(?:[^"\\]|\\[\s\S])*"|[^,{}"]*),)*"command":"(?:(?!run\.py(?:\\"|\x27)?[ ]+[a-z-])(?:[^"\\]|\\[\s\S]))*run\.py(?:\\"|\x27)?[ ]+profile(?![A-Za-z0-9_-])'
---
