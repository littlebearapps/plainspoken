# Claude Code specifics for copy-audit

- The skill is manual-only (`disable-model-invocation: true`): run it as `/plainspoken:copy-audit`. It never triggers
  on its own.
- It can run the CLI and write only `.plainspoken/drafts/*`. Pasted text is saved there first so the checker has a
  file to read. If that write is refused, audit the text as given and report the lint step as skipped.
- `${user_config.profile}` may stay as the literal text when the plugin loads with `--plugin-dir`. The CLI treats the
  literal as the shipped default profile, so the audit still runs. See `docs/claude-code-facts.md`, section 3.
- Plugin options may not reach the shell the commands run in, so pass the profile on the command
  line (`--plugin-profile '${user_config.profile}'`). See `docs/claude-code-facts.md`, section 4.
- The plain-language gate can use a cold read: where the `plainspoken:cold-reader` agent is installed, start one with
  the two-line prompt the plain-language skill describes; otherwise read the text yourself as the profile's reader.
