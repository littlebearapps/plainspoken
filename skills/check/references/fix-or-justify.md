# Justify what you kept

Use this when `merge` reads UNRESOLVED and you will keep a failing WARN. `RUN` and `FILE` are as in SKILL.md.
`justify` takes `--plugin-profile '${user_config.profile}'` (single quotes); `judge-record` and `paths` don't.

1. **Write the template.** `RUN justify FILE --template --write --plugin-profile '${user_config.profile}'`. It writes
   the keyed justify file atomically and prints its path (the same path `RUN paths FILE` names as `justify`). It lists
   every failing WARN rule, JR-accepted ones included, and keeps the kind and reason already written for the
   current version of the article (a file for an older version carries nothing over). Exit 2 with
   no current report means the article changed since the last lint: go back to SKILL.md step 1 and run the check again
   (this rerun isn't a fix pass). Exit 2 with an INCOMPLETE report: rerun what merge names, then merge, then come back
   here.
2. **Fill every item** by editing that file. `kind` is one of the following, and the JR judge accepts it only when
   the test holds:
   - `voice`: the pattern is something the profile's calibration notes ask for, and your reason names the section.
     With no calibration notes in the profile, don't use `voice`.
   - `quote`: the evidence sits inside verbatim third-party text.
   - `load_bearing`: removing or reshaping it would lose information the reader needs (for example, the three items
     are the three real options).
   - `false_positive`: the rule's own text says this isn't a hit.
   - `format`: a structural element where the rule's pattern is the format itself. Only an FAQ, a table, a
     checklist or numbered steps.
   - `metric`: only for 12f, 7, 7d and 12d (article- or section-level measures), and the reason says why a fix
     pass (cut, join, split or restate) can't move it honestly. For a 7d WARN kept under the rhythm rule, name what
     joining or splitting those sentences in their own words would lose or add.

   `reason` is one specific sentence on one line about what the text is doing, true of every evidence item for that
   rule, not "reads fine". Never use `voice` for a phrase on a ban or WARN list. Justify only what you'd defend to
   the author; otherwise fix it with a fix pass. When unsure, the judge rejects.
3. **Review input.** `RUN justify FILE --review-input --plugin-profile '${user_config.profile}'`. Exit 1 lists shape
   errors, or says there is nothing to review because no item covers a failing WARN rule: fix the file.
4. **One JR judge.** Start one `plainspoken:tells-judge` subagent with that output as its prompt input (same wording as
   the other judges). Record only the JSON object of its reply, as in SKILL.md step 4, with `--group JR`. Exit 1 →
   start the judge again once; a second failure → stop and report the reason.
5. **Merge.** `RUN merge FILE --plugin-profile '${user_config.profile}'`. A JR reject leaves that rule UNRESOLVED, even
   if an alias partner was accepted. You may rewrite that reason once (edit the file, then repeat steps 3 to 5); or
   fix the text with a fix pass if any remain. A second reject, or no passes left: stop and report the report path
   and the unresolved rule ids. Justify and JR never edit the article, so this isn't a fix pass.
