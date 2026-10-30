# Claude Code specifics for reader-value

- The skill is manual-only (`disable-model-invocation: true`). Run it as `/plainspoken:reader-value outline <file>`
  before drafting and `/plainspoken:reader-value deliver <draft>` before the piece ships. It never triggers on its
  own.
- The reviewer is the `plainspoken:delivery-checker` subagent. Start it with the Agent tool, one agent per run, and
  give it only the prompt SKILL.md deliver step 3 names. It's read-only (Read, Grep, Glob) and runs without the
  project's CLAUDE.md. Save only the JSON object of its reply (first `{` to last `}`) with the Write tool at the
  `delivery-reply` path, then record it; never paste the reply into a shell command (Claude Code's shell check
  refuses JSON in a heredoc). On a second round the reply file already exists, and Write refuses to overwrite a
  file not read this session: read it first, then write the new reply over it.
- Chain one step's CLI calls with `&&` in one Bash call: `paths` and `deliver-input` in one chain for deliver step 3.
  The CLI grant covers each part, so the chain runs without a prompt. `&&` stops at the first call that fails, so the
  exit code and the last lines are that call's: act on them, then run the rest again. No `;`, no pipes, no shell
  loops, and nothing else chained onto a CLI call (no `; echo`, `; ls` or `; cat`).
- Save the contract with the Write tool under `.plainspoken/reader-value/`, and fix it with the Edit tool. Both are
  allowed without a prompt there, and so is writing the reviewer's reply under `.plainspoken/reports/`. A contract
  in a file the user names elsewhere, and any edit to the draft itself, asks for permission as usual.
- `RUN reader-value template` prints the starter contract. Write it to the contract path with the Write tool; don't
  redirect the output with `>` in the shell.
- Figures go to the claims skill: `/plainspoken:claims <draft>` builds and checks the claim ledger.
- `${user_config.profile}` may stay as the literal text when the plugin loads with `--plugin-dir`. The CLI treats the
  literal as the shipped default profile, so the first step's profile call still runs. See
  `docs/claude-code-facts.md`, section 3. The `reader-value` subcommands don't read the profile.
