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
| Tool-call check | Before a tool call sends writing (an email, a post, a message), its text is linted: `warn`, `block-once` or `ask` | Claude Code, Cowork, Codex, Hermes | off |
| Paste-in text | The same rule, for apps that can't run hooks | claude.ai chat, ChatGPT chat | — |

## Steps

1. **Status.** Run `RUN setup --host <host> --status` and show the person what's on now. The host is the app this
   session runs in: `claude-code` here, `codex` in Codex or ChatGPT Work, `hermes` in Hermes Agent. If the person
   named a host in the arguments, use that one.
2. **For claude.ai or ChatGPT chat**, run `RUN setup --host claude-ai` (or `chatgpt`), show the printed text and
   where to paste it, and stop. Nothing is written. Add `--locale en-GB` or `--locale en-US` if the person writes in
   British or American English: the text gains one line saying so.
3. **Ask once.** Recommend: nudge on, drafting rule on (Claude Code only), lint after edits on, the tool-call check
   left as it is unless the person asks for it (then `warn`; `block-once` holds a send back first), scope `project`
   (Hermes: scope `user`, because Hermes runs plugins outside the project folder and reads the user-wide file).
   Scope `user` applies in every project on this machine, but only where plainspoken is installed. Ask the person to
   confirm or change these in one message. Don't change anything they didn't agree to.
4. **Preview.** Run `RUN setup --host <host> --scope <scope> --nudge on|off [--rule on|off] --lint-watch on|off
   [--tool-call off|warn|block-once|ask] --dry-run` and show the file it would write.
5. **Apply.** Run the same command without `--dry-run`. Show the status it prints and the line after it (start a new
   session; in Codex, trust the plugin's hooks with `/hooks`).
6. **Undo,** when asked: `RUN setup --host <host> --scope <scope> --remove`. It deletes only the lines setup wrote.

To change which English the skills write in, add `--locale en-AU|en-GB|en-US` to steps 4 and 5 when the person
asks. It writes `[locale] variant`; a project's file beats the voice profile, and the user-wide one doesn't.

Any setup call can end with host-check warnings (under `Host checks`; nothing at all on a healthy machine). Pass
each on to the person with its fix, in one line, and don't act on them: the person decides. A last line saying
`doctor --host <host> lists N things to confirm by hand` points at `/plainspoken:doctor`; mention it, don't run it.
For claude.ai and ChatGPT, the `Host checks` lines (no shell there) are on stderr: tell the person, but keep them
out of the text to paste. If a call prints `plainspoken needs Python 3.11 or newer`, pass that line on and stop.

Never edit `CLAUDE.md`, `AGENTS.md` or any other instructions file. Setup writes one config file and nothing else.

Setup doesn't choose a voice profile, and the user-wide file can't. If the person asks, point them to
`/plainspoken:voice build` and `guides/voice-profiles.md`: a profile is switched on per project folder (in Hermes
Agent, per Hermes profile's working folder).
