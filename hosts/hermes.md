# plainspoken in Hermes Agent

The skills are written for Claude Code. The plugin loads this note into the first turn of every session; apply it
whenever you use a plainspoken skill. Where this note and a skill disagree about *how* to run something, this note
wins in Hermes; the skill still decides *what* to do.

## Paths and commands

- `${CLAUDE_PLUGIN_ROOT}` means the plugin's root folder, given at the top of this note (it holds `lib/run.py`). It
  is also two folders above the `[Skill directory: …]` a loaded skill shows. Hermes doesn't fill it in, so write the
  absolute path into every command. `RUN` in the skills is `python3 <root>/lib/run.py`, run with `terminal`.
- Keep `--plugin-profile '${user_config.profile}'` exactly as written, single quotes and all. The engine reads that
  literal as the shipped default profile, and a project's `.plainspoken/config.toml` still picks its own.
  `--plugin-locale '${user_config.locale}'` works the same way: the literal counts as unset. To write in British or
  American English, set `[locale] variant` in a config file (`RUN setup --host hermes --locale <variant>` with
  `--scope user`).
- Claude Code tool names map as: Read → `read_file`, Write → `write_file`, Edit → `patch`, Bash → `terminal`,
  Grep/Glob → `search_files`. `allowed-tools`, `argument-hint` and `disable-model-invocation` are Claude Code
  settings; the nine manual-only skills (`adapt`, `claims`, `copy-audit`, `doctor`, `kaizen`, `reader-value`,
  `register-check`, `setup`, `voice`) still start only when the user asks.
- Another skill named as `/plainspoken:<name>` loads with `skill_view("plainspoken:<name>")`. If that returns not
  found, read `<root>/skills/<name>/SKILL.md` and follow it.
- Run every engine call from the project root (`cd` there first), as the skills say. Report files are keyed to it.

## Agents (the judges and checkers)

When a skill says to start a `plainspoken:<agent>` subagent (`tells-judge`, `claims-checker`, `delivery-checker`,
`cold-reader`), run that agent as its own one-shot Hermes process instead. It starts with a fresh context, so it
never sees this session. Never do an agent's job yourself: the skills' rule that you don't award your own pass holds
here too.

1. Build the prompt. Pipe the agent's input into `RUN agent-prompt <agent>`, which prepends the agent's
   instructions and the opener the skill names. For the check skill's judges, `--line N` picks judge N from
   `judge-input`'s four lines:

   ```bash
   T=$(mktemp -d)
   RUN judge-input "FILE" --plugin-profile '${user_config.profile}' > "$T/input.jsonl"  # exit 1 or 3: see check step 2
   RUN agent-prompt tells-judge --line 1 < "$T/input.jsonl" > "$T/J1.prompt"    # and --line 2, 3, 4
   ```

   The claims checker's input comes from `RUN claims checker-input …`, the delivery checker's from
   `RUN reader-value deliver-input …` (no `--line` for either), and the cold reader's is its two lines
   (`Reader: …`, `File: …`) passed on stdin.
2. Run it with the file tools only:

   ```bash
   hermes chat --query-file "$T/J1.prompt" --oneshot -Q -t file --source tool | RUN agent-reply > "$T/J1.json"
   ```

   `--source tool` keeps these runs out of the user's session lists. The judge inherits your profile through
   `HERMES_HOME` (`-p <profile>` overrides it) and starts in the shell's working folder unless the profile sets
   `terminal.cwd`, so run it from the project root without a different `-p`, or it reads another profile's config.
   The four judges can run at once (end each line with `&`, then `wait`). Each takes a minute or so. Hermes has no
   read-only toolset (`-t file` includes `write_file` and `patch`), so the agent's "never edit a file" rule is an
   instruction it follows, not a sandbox. If `hermes chat` can't run, use `delegate_task` with the prompt file's
   contents as the goal, and say so in the report.
3. Record it with the skill's own record step, reading from your file instead of the `reply` path:
   `RUN judge-record "FILE" --group J1 --from "$T/J1.json"` (or `claims record … --from`, `reader-value deliver …
   --from`). The record step validates the reply; a stale or invalid one means starting that agent again, as the
   skill says.

## What's different from Claude Code

- Hooks: after each `write_file` or `patch`, the lint and the claims integrity check report on the file, appended to
  the tool's result; the optional writing nudge is added to a turn that asks for writing. Before each `terminal`
  command, the publish gate checks a `git push` and the write guard stops a shell write to a reply file or the claims
  ledger (write those with `write_file` or `patch`). A block comes back as the command's result: do what it says,
  don't work around it. The gate's strictness comes only from `[gate] strictness` in `.plainspoken/config.toml`; a
  warn goes to the person and the command runs. Warn and block need `[gate] paths`; with none set, the gate only
  tells the person that nothing is gated. At the end of a turn, the kaizen nudge tells the person when proposals wait
  or calibrate is due; Claude Code's report guard (write's step 8 owner asks) isn't wired here. Still run the
  check skill yourself before anything goes out: the gate covers `terminal` only.
- The tool-call check (off unless `[tool_call] mode` is set, usually in the user-wide file): before any tool but the
  core ones (terminal, files, browser, memory, the task board), the writing in its arguments is linted in a separate
  process. `warn` posts one line to the person and adds the findings to the tool's result. `block-once` (and `ask`,
  which works the same here) blocks the first try with the findings as the result: remove what's flagged, never add
  facts, and call again; the same text sent again goes through. A tool named `…draft…` is only warned. If the lint
  fails or takes over 10 seconds, the call goes ahead.
- The chat-reply check (off unless `[chat_reply] mode = "warn"`, usually in the user-wide file): after a turn whose
  prompt asked for writing, `post_llm_call` lints a draft in the final reply in a separate process and posts one
  plain-text message to the person, never to you, and the reply is never changed. Over Telegram, Discord, Slack or
  Matrix it's a separate bot message; on the desktop app and the terminal app, a notice. In the classic CLI
  (`hermes chat`) it's printed at the end of the next turn, a turn late. Cron turns are skipped. Where Hermes refuses
  the post (no conversation, `plugins.isolation: host`), the message goes to Hermes' log instead, with the few words
  of the draft each finding quotes, as the kaizen nudge's fallback does.
- `[integrity] mode = "block"` works as a warning here: the finding reaches you after the edit, but Hermes can't hold
  the edit back, so fix it before going on. A lint or integrity hook that can't start, times out or prints something
  unreadable says so in one line, and that check didn't run on the file.
- No kaizen backstop: the agents run as their own `hermes chat` processes, so no hook here sees one finish.
  `kaizen report` shows 0 judge replies returned; the recorded count still holds.
- A nudge or lint line in your context comes from those hooks. Follow it the same way: lint a short draft with
  `RUN check - < draft`, run the check skill on a long one, and remove what's flagged without adding facts.
- No install-time settings. Pick a voice profile with `[engine] profile = "<name>"` in the project's
  `.plainspoken/config.toml` (see the README); turn the nudge on with the setup skill (`RUN setup --host hermes
  --scope user --nudge on` for every session of this profile). Kaizen records go to `.plainspoken/` in the project.
- The project is the Hermes profile's working folder (`terminal.cwd` in its `config.yaml`). Put
  `.plainspoken/config.toml` and `.plainspoken/profiles/<name>.toml` there, once per Hermes profile. The user-wide
  file can't pick a profile; `PLAINSPOKEN_PROFILE` can, but it beats every project's config
  (`guides/voice-profiles.md`).
- Agents run on this profile's default model (`hermes chat -m <model>` picks another), not the model the agent file
  names.
- The doctor skill (or `RUN doctor --host hermes`) checks python3, the plugin files, the config files and whether
  `hermes` is on PATH (without running it), and lists what it can't see for you to confirm (the `hermes chat`
  flags, the profile, the working folder, the toolsets). It only reports; the person decides what to change.
