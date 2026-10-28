# plainspoken in Codex

The skills are written for Claude Code. Read this once, before the first step of any plainspoken skill, and apply it
for the rest of the session. Where this note and a skill disagree about *how* to run something, this note wins in
Codex; the skill still decides *what* to do.

## Paths and commands

- `${CLAUDE_PLUGIN_ROOT}` means the plugin's root folder: two folders above the `SKILL.md` you loaded (the skills
  list gives its path). It holds `lib/run.py`. Codex doesn't fill it in, so write the absolute path into every
  command. `RUN` in the skills is `python3 <root>/lib/run.py`.
- Keep `--plugin-profile '${user_config.profile}'` exactly as written, single quotes and all. The engine reads that
  literal as the shipped default profile, and a project's `.plainspoken/config.toml` still picks its own.
  `--plugin-locale '${user_config.locale}'` works the same way: the literal counts as unset. To write in British or
  American English, set `[locale] variant` in a config file (`RUN setup --host codex --locale <variant>`).
- `allowed-tools`, `argument-hint` and `disable-model-invocation` in the frontmatter are Claude Code settings. Codex
  ignores them. The nine manual-only skills (`adapt`, `claims`, `copy-audit`, `doctor`, `kaizen`, `reader-value`,
  `register-check`, `setup`, `voice`) still start only when the user asks.
- Another skill named as `/plainspoken:<name>` is `$plainspoken:<name>` here. If it doesn't load, read
  `<root>/skills/<name>/SKILL.md` and follow it.
- Run every engine call from the project root, as the skills say. Report files are keyed to it.

## Agents (the judges and checkers)

When a skill says to start a `plainspoken:<agent>` subagent (`tells-judge`, `claims-checker`, `delivery-checker`,
`cold-reader`), give that agent a fresh context so it never sees this session. Never do an agent's job yourself:
the skills' rule that you don't award your own pass holds here too.

1. Build the prompt. Pipe the agent's input into `RUN agent-prompt <agent>`, which prepends the agent's
   instructions and the opener the skill names. For the check skill's judges, `--line N` picks judge N from
   `judge-input`'s four lines:

   ```bash
   T=$(mktemp -d)
   RUN judge-input "FILE" --plugin-profile '${user_config.profile}' > "$T/input.jsonl"  # exit 1: see check step 2
   RUN agent-prompt tells-judge --line 1 < "$T/input.jsonl" > "$T/J1.prompt"    # and --line 2, 3, 4
   ```

   The claims checker's input comes from `RUN claims checker-input …`, the delivery checker's from
   `RUN reader-value deliver-input …` (no `--line` for either), and the cold reader's is its two lines
   (`Reader: …`, `File: …`) passed on stdin.
2. Run it with `spawn_agent` and `fork_turns: "none"` (a clean context; the default copies your whole session),
   giving the prompt file's contents as the agent's whole task, nothing added. Start the four judges together and
   wait for all four. The agent's "never edit a file" rule is an instruction here, not a sandbox.

   When this session runs outside Codex's sandbox (or the user approves running it there), a separate process gives
   the agent a real read-only sandbox instead. Inside the sandbox it fails, because Codex's own folder is read-only:

   ```bash
   codex exec --sandbox read-only --ephemeral --skip-git-repo-check -C "$PWD" -o "$T/J1.out" - < "$T/J1.prompt"
   ```
3. Save the agent's reply to a file and cut it to the JSON object: `RUN agent-reply < "$T/J1.out" > "$T/J1.json"`.
   Then record it with the skill's own record step, reading from that file instead of the `reply` path:
   `RUN judge-record "FILE" --group J1 --from "$T/J1.json"` (or `claims record … --from`, `reader-value deliver …
   --from`). The record step validates the reply; a stale or invalid one means starting that agent again, as the
   skill says.

## What's different from Claude Code

- Hooks (`hooks/codex.json`): after each `apply_patch` edit, the lint and the claims integrity check report on the
  patched files; the optional writing nudge names the right step when a prompt asks for writing. Before each shell
  command, the publish gate checks a `git push` and the write guard stops a shell write to a reply file or the claims
  ledger (write those with `apply_patch`). At the end of a turn, the kaizen nudge tells the person when proposals
  wait or calibrate is due; Claude Code's report guard (write's step 8 owner asks) isn't wired here. Codex runs
  them only after the user trusts them (`/hooks`), and calls tool hooks a guardrail, not a complete boundary, so
  still run `$plainspoken:check` yourself before anything goes out.
- Re-trust after every update. Since Codex 0.164.0, the trust is tied to a hash of every file in the plugin, so any
  plainspoken update, not only a change to its hooks, puts all of them back to "needs review". Until the user opens
  `/hooks`, reviews them and trusts them again, Codex skips them: nothing blocks, but nothing lints either.
- The tool-call check (off unless `[tool_call] mode` is set): before an MCP tool call, the writing in its arguments
  is linted. `warn` shows the person one line and gives you the findings, which you read next to the tool's result,
  after the call has run. `block-once` holds the first try back with the findings: remove what's flagged, never add
  facts, and call again; the same text sent again goes through. `ask` works as `block-once` here. A tool named
  `…draft…` is only warned.
- The publish gate takes its strictness only from `[gate] strictness` in `.plainspoken/config.toml` (Codex has no
  plugin options): `block` denies the push, `warn` shows a message and lets it go, and with no file it does nothing.
  `warn` and `block` need `[gate] paths`; with none set, the gate only shows a message that nothing is gated.
- No kaizen backstop: Codex starts the agents with `spawn_agent` or `codex exec`, and a plugin can't add agent types,
  so no hook sees a plainspoken agent finish. `kaizen report` shows 0 judge replies returned here; the recorded
  count still holds.
- A nudge or lint line in your context comes from those hooks. Follow it the same way: lint a short draft with
  `RUN check - < draft`, run `$plainspoken:check` on a long one, and remove what's flagged without adding facts.
- No install-time settings. Pick a voice profile with `[engine] profile = "<name>"` in the project's
  `.plainspoken/config.toml` (see the README); turn the nudge on with `$plainspoken:setup` (`RUN setup --host codex
  …`). Kaizen records go to `.plainspoken/` in the project.
- Agents run on your Codex model, not the model the agent file names.
- `$plainspoken:doctor` (or `RUN doctor --host codex`) checks python3, the plugin files, the config and whether
  `codex` is on PATH, and lists what it can't see for you to confirm (hook trust, sandbox writes, the judges'
  tools). It only reports; the person decides what to change.
