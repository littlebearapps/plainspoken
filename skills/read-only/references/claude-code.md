# Claude Code specifics for read-only

- The skill has no `disable-model-invocation`, so the model can start it, and so can another skill or an agent
  workflow: `/plainspoken:read-only register-check draft.md`. The five skills it runs stay manual-only.
- Its `allowed-tools` grants the CLI only, with no write. The list grants; it doesn't restrict, so a write isn't
  blocked: it goes through the normal permission check, and the person decides. How that behaves in `claude -p`:
  `docs/claude-code-facts.md`, section 9.
- The named skill's own `allowed-tools` don't apply here. You read its file; you don't start it, so its pre-approved
  writes (drafts, profiles, contracts, the ledger) aren't granted, and you don't make them.
- The checkers are the `plainspoken:claims-checker` and `plainspoken:delivery-checker` subagents. Start one with the
  Agent tool in the foreground, one per run, with only the prompt the named skill gives. Save only the JSON object
  of its reply (first `{` to last `}`) with the Write tool at the reply path, which asks the person first; never
  paste the reply into a shell command (Claude Code's shell check refuses JSON in a heredoc). On a second round the
  reply file already exists, and Write refuses to overwrite a file not read this session: read it first.
- Chain one step's CLI calls with `&&` in one Bash call, as the named skill's own `references/claude-code.md` says.
  No `;`, no pipes, no shell loops.
- `${user_config.profile}` may stay as the literal text when the plugin loads with `--plugin-dir`. The CLI treats the
  literal as the shipped default profile, so the check still runs. See `docs/claude-code-facts.md`, section 3.
