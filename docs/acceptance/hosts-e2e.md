# Codex and Hermes Agent: hands-on acceptance

Date: 2026-10-20 (Melbourne). Branch `feature/hosts-hermes-codex`. Codex CLI 0.163.0 (Linux), Hermes Agent v0.22.1
(Linux, git install). Fixture: a two-paragraph community-garden draft with seven planted tells in its first
paragraph (Nestled, in the heart of, vibrant, testament, Moreover, fostered, robust) and a plain second paragraph.
Every run used the shipped default profile and asked for the check to stop after the report (no fix or justify).

## Results

| Host | Install | Skill run | Judges | Verdict |
|---|---|---|---|---|
| Claude Code | (unchanged; v0.5.0 behaviour) | — | plugin subagents | — |
| Codex | local marketplace in a throwaway `CODEX_HOME`: `codex plugin marketplace add`, `codex plugin add plainspoken@<mkt>` | `$plainspoken:check` via `codex exec` (workspace-write) | 4 × `spawn_agent` after the nested `codex exec` failed | FAIL · coverage 41/41 · BLOCK 2, 4a · WARN 16, 7d, HM |
| Hermes | `hermes -p <test profile> plugins install <git url> --force`, then `plugins enable plainspoken` | the check skill via `hermes chat -q --oneshot` | 4 × `hermes chat --query-file … -t file` | FAIL · coverage 41/41 · BLOCK 2, 4a · WARN 16, 7d, HM |

Both hosts read their `hosts/<host>.md` note first, filled in the plugin root, kept `--plugin-profile
'${user_config.profile}'` literal (the engine used the default profile), built each judge's prompt with
`run.py agent-prompt tells-judge --line N`, cut each reply with `run.py agent-reply`, recorded it with `judge-record
--from` and merged. Neither touched the draft. The two verdicts are identical.

Standalone judge runs (one judge, prompt from `agent-prompt`, reply recorded by `judge-record`):
- `codex exec --sandbox read-only --ephemeral … -o <file> -` (model gpt-6.1-sol): valid J2 reply, recorded.
- `hermes chat --query-file <prompt> --oneshot -Q -t file`: valid J3 reply, recorded after `agent-reply` cut the
  trailing `session_id:` line.

## Findings

- **Codex: a nested `codex exec` can't start inside Codex's sandbox.** It fails with "failed to initialize in-process
  app-server client: Read-only file system", because the sandbox makes `CODEX_HOME` read-only. `hosts/codex.md`
  therefore starts the agents with `spawn_agent` and `fork_turns: "none"`, and keeps `codex exec` for sessions
  outside the sandbox. The agents' read-only rule is an instruction in that case.
- **Hermes: the install scan rates plainspoken "caution".** Any HIGH finding gives "caution", and a community source
  on "caution" needs the user to confirm (non-interactive installs refuse without `--force`). The remaining HIGH
  findings are the 10 skills' Claude Code load-time lines (`` !`python3 …` ``), which the scanner always rates
  HIGH, and one line in `docs/claude-code-facts.md`. Literal BOM characters and the backticks in the code-span regex
  were rewritten to clear their HIGH findings. Hermes' plugin scan reads no ignore file, so docs and tests are
  scanned too.
- **Hermes: `--enable` matches the plugin's manifest name.** Installed from a URL whose last segment isn't
  `plainspoken`, the plugin directory takes that name and `--enable` doesn't match it; `hermes plugins enable
  plainspoken` does. Installing from `littlebearapps/plainspoken` gives the directory the right name.
- **Hermes has no read-only toolset.** The judges get `-t file` (read, write, patch, search) and follow the agent
  file's "never edit" rule.
- Both hosts reported the engine's HM (human markers) WARN on a draft that uses "We"; that's the engine's rule, the
  same in Claude Code, not a host difference.

## Not tested

- Installing from GitHub (`codex plugin marketplace add littlebearapps/lba-plugins`, `hermes plugins install
  littlebearapps/plainspoken`): needs the merged branch and a re-pinned `lba-plugins` entry.
- The other skills (write, humanize, plain-language, claims, reader-value) in either host. They use the same paths,
  `!`…`` handling and agent recipe as check.
- Codex in the ChatGPT desktop app, and the Codex IDE extension (which doesn't load plugins).
