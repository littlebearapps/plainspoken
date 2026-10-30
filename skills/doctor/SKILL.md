---
name: doctor
description: Checks what plainspoken needs here (python3, its files, the config, the commands the judges use), lists each problem with its fix, and what to confirm by hand. Changes nothing. Manual only.
argument-hint: "[claude-code | codex | hermes | claude-ai | chatgpt]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py doctor *)
---

# plainspoken doctor

> Running in Codex or Hermes Agent? Read `../../hosts/codex.md` or `../../hosts/hermes.md` (relative to this
> skill's folder) once before step 1. In Claude Code, skip this note.

`RUN` is `python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py`. Run it from the project root.

Never fix, install, enable or edit anything, even when the fix looks small. The person decides what to do.

## Steps

1. **Run the checks.** Run `RUN doctor --host <host> --plugin-profile '${user_config.profile}' --plugin-locale '${user_config.locale}'`. The host is the app this session runs in: `claude-code`
   here, `codex` in Codex or ChatGPT Work, `hermes` in Hermes Agent. If the person named a host in the arguments, use
   that one. Each line is `ok`, `WARN` or `not checked`; it exits 0 even with warnings. If it prints `plainspoken
   needs Python 3.11 or newer` instead, pass that line on to the person and stop: nothing else can run.
2. **Fill in what you can see.** A `not checked` line that names something you can see yourself (your own tools, your
   permissions, whether you may run the Bash command it names) gets one line from you: whether you have it. Don't run
   anything to find out. Say nothing about the ones you can't see.
3. **Report.** Give the person each `WARN` with its fix, one line each. Then list the items that stayed unverified
   (the `not checked` lines you couldn't answer). Never call an unverified item fine.

For claude.ai or ChatGPT chat, the lines say there's no shell there: the lint, the judges and the hooks don't run,
and the paste-in text is guidance the model follows, not a check. Pass that on as it is.
