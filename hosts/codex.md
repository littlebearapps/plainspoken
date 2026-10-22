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
- `allowed-tools`, `argument-hint` and `disable-model-invocation` in the frontmatter are Claude Code settings. Codex
  ignores them. The manual-only skills (`claims`, `reader-value`, `kaizen`) still start only when the user asks.
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
  patched files; the optional writing nudge names the right step when a prompt asks for writing. Codex runs them only
  after the user trusts them (`/hooks`). There's no publish gate and no kaizen nudge, so run `$plainspoken:check`
  yourself before anything goes out.
- A nudge or lint line in your context comes from those hooks. Follow it the same way: lint a short draft with
  `RUN check - < draft`, run `$plainspoken:check` on a long one, and remove what's flagged without adding facts.
- No install-time settings. Pick a voice profile with `[engine] profile = "<name>"` in the project's
  `.plainspoken/config.toml` (see the README); turn the nudge on with `$plainspoken:setup` (`RUN setup --host codex
  …`). Kaizen records go to `.plainspoken/` in the project.
- Agents run on your Codex model, not the model the agent file names.
