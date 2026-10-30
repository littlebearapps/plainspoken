# Claude Code specifics for write

- The skill triggers on its own when someone asks for a draft. You can also run it as
  `/plainspoken:write <brief or notes file> [--type article|page|email|social]`.
- It can run the CLI without asking. Saving the draft (to the path the user names, or `.plainspoken/drafts/`) goes
  through the normal permission prompt.
- Step 7: start the check with the Skill tool as `plainspoken:check`, with the draft path as its argument (plus
  `--content-type social` for a social post). The check skill loads with its own allowed tools and starts its
  `plainspoken:tells-judge` subagents itself. If the Skill tool isn't available, follow
  `${CLAUDE_PLUGIN_ROOT}/skills/check/SKILL.md` step by step; its report-file writes will then ask for permission.
- Steps 2 and 6: `reader-value` and `claims` are manual-only (`disable-model-invocation: true`), so the Skill tool
  can't start them from here. Read `${CLAUDE_PLUGIN_ROOT}/skills/reader-value/SKILL.md` (outline mode) and
  `${CLAUDE_PLUGIN_ROOT}/skills/claims/SKILL.md` and follow their steps, with their own `references/claude-code.md`
  notes. Writing the contract under
  `.plainspoken/reader-value/`, the ledger, saved sources and the checker reply asks for permission, because this
  skill's allowed tools cover the CLI only. The claims checker is the `plainspoken:claims-checker` subagent, started
  with the Agent tool exactly as the claims skill's step 6 says, in the foreground: never `run_in_background`, and
  its reply read and recorded before the next step.
- Step 8: a Stop hook reads the report when the turn ends. If its `needs the owner` line lists nothing and the
  prose still asks the owner to check something, the hook sends the report back once, quoting the ask: cut the line
  or hold it `blocking` as step 6 says, then report again.
- `${CLAUDE_PLUGIN_ROOT}` is the plugin's folder, the one holding `lib/run.py`. The other skills' files are there,
  not in the project.
- `${user_config.profile}` may stay as the literal text when the plugin loads with `--plugin-dir`. The CLI treats the
  literal as the shipped default profile, so the skill still runs. See `docs/claude-code-facts.md`, section 3.
- Plugin options may not reach the shell the commands run in, so pass the profile on the command line
  (`--plugin-profile '${user_config.profile}'`). See `docs/claude-code-facts.md`, section 4.
- The skill drafts only. It never posts, sends or publishes; a request to publish is outside it.
- Run each `anchors` call on its own. A shell loop (`for t in …; do …; done`) is refused with "A variable in this
  command can't be checked before it runs"; the same goes for looping `cat` over the reference files (use Read).
