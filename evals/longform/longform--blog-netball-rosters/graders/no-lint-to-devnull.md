---
type: regex
target: trace
# Fails a run that loses the lint (#162). check prints it on stdout, so sending that to /dev/null or through tail fails; head keeps the counts line, and check's stderr isn't the lint. judge-input prints it on stderr, so 2>/dev/null, >/dev/null 2>&1 and 2>&1 | tail fail; its stdout going to a file doesn't. A claims call's 2>/dev/null doesn't count.
pattern: '(?:run\.py|\$[A-Za-z_]+)(?:\\"|\x27)?[ ]+(?:check (?:[^;&|\n"\\]|\\.)*?(?: (?:&|1)?>[ ]*/dev/null|[ ]?\|[ ]*tail[ ])|judge-input (?:[^;&|\n"\\]|\\.)*? (?:(?:&|2)>[ ]*/dev/null|>[ ]*/dev/null[ ]+2>&1|2>&1[ ]*\|[ ]*tail[ ]))'
match: not_contains
---
