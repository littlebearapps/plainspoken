## What

<!-- What this pull request changes, in a sentence or two. -->

## Why

<!-- The problem it solves. Link the issue if there is one. -->

## Testing

- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `python3 scripts/dev/leak_guard.py` finds nothing (no private names, no client text)
- [ ] `python3 scripts/dev/check_links.py .` passes
- [ ] `python3 scripts/dev/check_doc_commands.py .` passes
- [ ] `python3 scripts/dev/lint_frontmatter.py .` passes
- [ ] `claude plugin validate . --strict` passes
- [ ] Docs updated if this changes what a user sees or does
- [ ] The commit type is right (`feat`, `fix`, `docs`, …): release-please writes the CHANGELOG from it, so
      CHANGELOG.md isn't edited by hand

## Related issues

<!-- Fixes #123 -->
