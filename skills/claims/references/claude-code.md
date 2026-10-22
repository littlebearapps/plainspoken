# Claude Code specifics for claims

- The skill is manual-only (`disable-model-invocation: true`): run it as `/plainspoken:claims <article>`. It never
  triggers on its own.
- The checker is the `plainspoken:claims-checker` subagent. Start it with the Agent tool, one agent per run, and
  give it only the prompt SKILL.md step 6 names. It's read-only (Read, Grep, Glob) and runs without the project's
  CLAUDE.md. Save only the JSON object of its reply (first `{` to last `}`) with the Write tool, then record it;
  never paste the reply into a shell command (Claude Code's shell check refuses JSON in a heredoc). On a second
  round the reply file already exists, and Write refuses to overwrite a file not read this session: read it first,
  then write the new reply over it.
- Make one Bash call per command: one Bash call per RUN line, no shell loops, no `&&` chains over several
  claims, no `for` over sources, and nothing chained onto a CLI call (no `; echo`, `; ls` or `; cat`). Each call's
  exit code is what the step acts on.
- Edit the ledger with the Edit tool only, one claim at a time: never a heredoc, a helper script or a `python3 -`
  call, even to move several anchors at once (the shell check refuses them, and the ledger is yours to read back).
- The hash and the clock come from the CLI: `RUN claims stamp ARTICLE` writes `source_content_hash`, `checked_at`
  and `checked_by` into the ledger. Don't run `date` or write a script for them.
- Fetch sources with the host's fetch tool (or a fetch MCP server you have), then save the text with the Write tool
  under `.plainspoken/sources/`. The skill itself never fetches.
- Allowed without a prompt: the CLI, writes under `.plainspoken/sources/` and `.plainspoken/claims/`, edits under
  `.plainspoken/claims/`, and the checker reply under `.plainspoken/reports/`. A `[claims] ledger_dir` or
  `sources_dir` set elsewhere, and any edit to the article itself, asks for permission as usual.
- `${user_config.profile}` may stay as the literal text when the plugin loads with `--plugin-dir`. The CLI treats the
  literal as the shipped default profile, so the first step's profile call still runs. See
  `docs/claude-code-facts.md`, section 3. The `claims` subcommands don't read the profile.
