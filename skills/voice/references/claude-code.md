# Claude Code specifics for voice

- `${user_config.profile}` may stay as the literal text when the plugin loads with `--plugin-dir`. The CLI treats the
  literal as the shipped default profile, so a build, apply or check still runs. See `docs/claude-code-facts.md`,
  section 3.
- Plugin options may not reach the shell the injection line or the commands run in. Pass the profile on the command
  line (`--plugin-profile '${user_config.profile}'`) and don't read it from the environment. See
  `docs/claude-code-facts.md`, section 4.
- The skill is manual-only (`disable-model-invocation: true`). Its `allowed-tools` pre-approve writes to
  `.plainspoken/profiles/*.toml` and `.plainspoken/samples/*`. The list grants; it doesn't restrict. Any other
  write, such as saving an Apply rewrite over the draft, goes through the normal permission check (how that
  behaves in `claude -p`: `docs/claude-code-facts.md`, section 9).
