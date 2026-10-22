# Claude Code specifics for adapt

- The skill is manual-only (`disable-model-invocation: true`): run it as `/plainspoken:adapt <file or pasted text>
  <platform...>`. It never triggers on its own.
- It can run the CLI and write only `.plainspoken/drafts/*`. Pasted text is saved there first so the checker has a
  file to read. If that write is refused, work on the text as given, show the drafts in the reply and report the
  lint step as skipped.
- `${user_config.profile}` may stay as the literal text when the plugin loads with `--plugin-dir`. The CLI treats the
  literal as the shipped default profile, so the checks still run. See `docs/claude-code-facts.md`, section 3.
- Plugin options may not reach the shell the commands run in, so pass the profile on the command line
  (`--plugin-profile '${user_config.profile}'`). See `docs/claude-code-facts.md`, section 4.
- The skill never posts, so there is nothing to approve beyond the two permissions above. A request to publish a
  draft is outside it.
