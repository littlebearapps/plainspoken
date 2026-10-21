---
name: setup
description: Turns plainspoken's optional pieces on or off for this app (the writing nudge, the drafting rule, lint after edits), or prints the text to paste into claude.ai or ChatGPT. Manual only.
argument-hint: "[claude-code | codex | hermes | claude-ai | chatgpt] [--scope project|user] [status | remove]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py setup *)
---

# plainspoken setup

> Running in Codex or Hermes Agent? Read `../../hosts/codex.md` or `../../hosts/hermes.md` (relative to this
> skill's folder) once before step 1. In Claude Code, skip this note.

`RUN` is `python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py`. Run it from the project root.

## The pieces

| Piece | What it does | Where it runs | Default |
|---|---|---|---|
| Writing nudge | When a prompt asks for an email, text, post, script, page or a rewrite, one line names the plainspoken step that fits | Claude Code, Cowork, Codex (CLI, app, ChatGPT Work), Hermes | off |
| Drafting rule | Every session starts with a short rule: use plainspoken whenever something people will read is drafted | Claude Code, Cowork | off |
| Lint after edits | After a draft file is saved, the lint's findings come straight back | Claude Code, Cowork, Codex, Hermes | on |
| Paste-in text | The same rule, for apps that can't run hooks | claude.ai chat, ChatGPT chat | — |

## Steps

1. **Status.** Run `RUN setup --host <host> --status` and show the person what's on now. The host is the app this
   session runs in: `claude-code` here, `codex` in Codex or ChatGPT Work, `hermes` in Hermes Agent. If the person
   named a host in the arguments, use that one.
2. **For claude.ai or ChatGPT chat**, run `RUN setup --host claude-ai` (or `chatgpt`), show the printed text and
   where to paste it, and stop. Nothing is written.
3. **Ask once.** Recommend: nudge on, drafting rule on (Claude Code only), lint after edits on, scope `project`.
   Scope `user` applies in every project on this machine, but only where plainspoken is installed. Ask the person to
   confirm or change these in one message. Don't change anything they didn't agree to.
4. **Preview.** Run `RUN setup --host <host> --scope <scope> --nudge on|off [--rule on|off] --lint-watch on|off
   --dry-run` and show the file it would write.
5. **Apply.** Run the same command without `--dry-run`. Show the status it prints and the line after it (start a new
   session; in Codex, trust the plugin's hooks with `/hooks`).
6. **Undo,** when asked: `RUN setup --host <host> --scope <scope> --remove`. It deletes only the lines setup wrote.

Never edit `CLAUDE.md`, `AGENTS.md` or any other instructions file. Setup writes one config file and nothing else.
