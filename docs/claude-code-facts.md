# Claude Code facts (empirical probes)

Probed 2026-10-10 on Claude Code CLI 2.1.296 (`claude --version`), Linux, `claude -p` on the subscription.
Scratch plugin `/tmp/ps-probe/plugin` (loaded with `--plugin-dir`, no install step), scratch project `/tmp/ps-probe/proj`
(its `CLAUDE.md` holds `MARKER-7731`). Neither is committed.

Note: `--allowedTools` is variadic and swallows a following positional prompt
(`Error: Input must be provided either through stdin or as a prompt argument`). Put the prompt first, or use `--`.

## 1. Does `if: "Edit(*.md)"` fire for a Write of `post.md`?

Command (from `proj/`):

```
claude -p --plugin-dir /tmp/ps-probe/plugin --permission-mode acceptEdits \
  "Write the file post.md containing 'hello', then write notes/a.txt containing 'hi', then write other.txt containing 'x'."
```

Result: **No.** Only the unconditioned `all` hook fired, three times (`post.md`, `notes/a.txt`, `other.txt`, each with an
absolute `tool_input.file_path`). No `out-if-md-*.json` was written, so `if: "Edit(*.md)"` did not fire for a Write of `post.md`.

The raw output files of the Write run were not kept (cleared before the next run); only the Edit-run files survive.

Follow-up probe: `Use the Edit tool to change 'hello' to 'howdy' in post.md.` produced both `out-if-md-*.json`
(`file_path: /tmp/ps-probe/proj/post.md`) and `out-all-*.json`. So `Edit(*.md)` matches the Edit tool only, not Write.

Consequences:
- To cover Write and Edit with `if`, use two hook entries (`Write(*.md)` and `Edit(*.md)`), or drop `if` and filter on
  `tool_input.file_path` inside the hook script. Not tested here: `Write(*.md)`, and whether the pattern matches
  absolute paths for non-`.md` files (`notes/a.txt` and `other.txt` were never given an `if` hook that could skip them,
  because the Write run never matched `Edit(*.md)` at all).
- The safe design is no `if`, with the script filtering by extension.

## 2. Which `CLAUDE_PLUGIN_OPTION_*` variables reach a hook, and how `multiple: true` is encoded

Same hook run as Q1. Hook process env (all `CLAUDE_*` vars, trimmed to the relevant ones):

```
CLAUDE_PROJECT_DIR=/tmp/ps-probe/proj
CLAUDE_PLUGIN_ROOT=/tmp/ps-probe/plugin
CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/probe-inline
CLAUDE_CODE_SESSION_ID=<uuid>   CLAUDE_CODE_ENTRYPOINT=sdk-cli   CLAUDE_EFFORT=high   (plus other CLAUDE_CODE_* runtime vars)
```

Result: **No `CLAUDE_PLUGIN_OPTION_*` variables at all**, for either `profile` or `targets`. With `--plugin-dir` (no install
step) the manifest defaults are not populated into the hook env. The encoding of a `multiple: true` value is therefore
**not observed**; it needs an installed plugin with userConfig set (not done: installing plugins is out of scope).
Plan code must not assume the vars exist: read them with a fallback to built-in defaults. Re-probed on an installed
copy in section 11: a set option does reach the hooks there.

## 3. Do `${user_config.profile}`, `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_SKILL_DIR}` substitute in SKILL.md?

Command:

```
claude -p "/probe:probe" --plugin-dir /tmp/ps-probe/plugin --permission-mode acceptEdits --allowedTools "Bash(env *)"
```

Result (model's report of the rendered skill, two runs agree):
- `${user_config.profile}`: **not substituted**, stays the literal `${user_config.profile}` (not the manifest default `default`).
- `${CLAUDE_PLUGIN_ROOT}`: reported as substituted; corroborated only by the hook env (below), not by a printed skill value.
- `${CLAUDE_SKILL_DIR}`: **unverified.** The model said it was substituted but paraphrased and never printed the value.

The second run was asked to quote verbatim, but the assistant text only confirmed "substituted to real paths" and did not
print them. The hook env in Q2 shows `CLAUDE_PLUGIN_ROOT=/tmp/ps-probe/plugin`, which is the expected value.

## 4. Does `` !`…` `` injection run in a plugin skill? Does it see `CLAUDE_PLUGIN_OPTION_*`? Does Bash?

Same command as Q3.

- Injection ran (the `injected env:` line was followed by empty output, `Bash completed with no output`). It printed
  **nothing** for `env | grep -E '^CLAUDE_(PLUGIN|PROJECT)'`, so the injection shell saw **no** `CLAUDE_PLUGIN_*` or
  `CLAUDE_PROJECT_*` variables (not even `CLAUDE_PLUGIN_ROOT`, which hooks do get). Treat `${CLAUDE_PLUGIN_ROOT}`
  text substitution, not env, as the way to reach the plugin root from a skill.
- Bash tool: `env | grep CLAUDE_PLUGIN_OPTION || echo none` printed `none`. No `CLAUDE_PLUGIN_OPTION_*` in the Bash
  tool environment (consistent with Q2: nothing is populated under `--plugin-dir`).
- The skills no longer use injection (#12, 2026-10-21). Hermes' install scan rates any load-time command under
  `skills/` high, so each skill now runs the same `run.py` call, with the same flags, as its explicit first step.

## 5. With `omitClaudeMd: true`, does a plugin agent see the project CLAUDE.md?

Command (from `proj/`): `claude -p "Use the probe:probe-agent agent and report its answer verbatim." --plugin-dir /tmp/ps-probe/plugin`

Result: the agent answered **`visible`**. The agent ran as `subagent_type: probe:probe-agent` (confirmed in stream-json),
so `omitClaudeMd: true` in a plugin agent's frontmatter did **not** hide the project `CLAUDE.md` here. Either the field is
ignored for plugin agents, or it is not honoured in this version/mode. Judge isolation must not rely on it: pass the
judge only what it needs and treat project instructions as potentially visible.

## Summary

| # | Question | Answer |
|---|---|---|
| 1 | `if: "Edit(*.md)"` on Write of `post.md` | Did not fire. It fires for the Edit tool only. |
| 2 | `CLAUDE_PLUGIN_OPTION_*` in hooks | None present under `--plugin-dir`; `multiple` encoding unobserved. |
| 3 | SKILL.md substitution | `${user_config.*}` literal; `${CLAUDE_PLUGIN_ROOT}` substituted (hook env corroborates); `${CLAUDE_SKILL_DIR}` unverified. |
| 4 | `` !`…` `` and Bash env | Injection runs; no `CLAUDE_PLUGIN_*` or `OPTION_*` visible to it or to Bash. |
| 5 | `omitClaudeMd: true` | Agent still saw `MARKER-7731` (`visible`). |
| 6 | `if: "Bash(git push*)"` / `"Bash(git *)"` | Push filter misses `git -C x push`; `git *` catches that and `cd x && git push` but not `env git push`. Gate registered with no `if`; its own parser and limits are listed in section 6. |

## 6. Does `if: "Bash(git push*)"` fire only for `git push`?

Probed 2026-10-10, Claude Code CLI 2.1.296. Scratch plugin `/tmp/ps-probe2/plugin` (PreToolUse, matcher `Bash`,
`if: "Bash(git push*)"`, a script that appends `tool_input.command` to a log), scratch repo with a bare remote and one
unpushed commit. Command (from the repo):

```
claude -p "Run 'git status' then run 'git push' using the Bash tool, one after the other. Report briefly." \
  --plugin-dir /tmp/ps-probe2/plugin --permission-mode acceptEdits --allowedTools "Bash(git *)"
```

Result: the log held exactly one line, `git push`. `git status` did not trigger the hook. The filter works for a plain
`git push`, but the follow-up probe below found pushes it misses, so the publish gate has **no `if`** (decision below)
and parses the command itself.

Follow-up probe (same day, scratch plugin `/tmp/ps-probe3/plugin`, two handlers on one script: `if: "Bash(git push*)"`
logged as `push`, `if: "Bash(git *)"` logged as `gitstar`; same method, prompt first, `--allowedTools "Bash(*)"` last):

| Command run | `Bash(git push*)` | `Bash(git *)` |
|---|---|---|
| `cd /tmp/ps-probe3/proj && git push` | fired (logged command: `git push`) | fired |
| `echo c>c; git add c; git commit -qm c && git -C <repo> push` | did not fire | fired (logged the whole compound) |
| `FOO=1 git push` | fired (the harness strips the assignment) | fired |
| `env git push` | did not fire | did not fire |

`Bash(git *)` covers `cd x && git push` and `git -C x push`, but not `env git push` (and by the same logic
`sudo git push`), so an `if` filter leaves a bypass. Decision: register the gate with **no `if`**. The script exits
before importing anything beyond sys/os/json when the command has neither "push" nor "git" (a git alias can hide a
push), or when the plugin option says watch and the project has no `.plainspoken/config.toml` (whose `[gate]
strictness` would beat it). It parses the command itself (`hooks/_pushcmd.py`: a small shell lexer, then a scan for git past wrappers and keywords).
Because the gate runs on every Bash call, it has no `onFailure: "block"` (a missing `python3`, a timeout or a Windows host would block every command for users who never opted in). The fail-closed guarantee lives in the script: in block mode every internal error is a deny.

### What the gate checks, and its limits

Scope: an opt-in guardrail against *accidental* pushes of unchecked writing, not a security boundary. Block mode
denies anything it can't interpret; it must not deny ordinary push commands.

- **Finding the push** (`hooks/_pushcmd.py`). Quotes, escapes, `$(…)`, backticks, `${…}`, comments and redirections
  (`2>&1`, `>log`, `&>/dev/null`) are lexed, and heredoc bodies are read as data. A simple command runs git when its
  command word is `git` after assignments, wrappers (`sudo`, `env`, `nice`, `time`, `nohup`, `command`, `exec`,
  `timeout <n>`) and compound keywords (`if`, `then`, `do`, `{`, `!`, …). `sh -c`/`bash -c` strings, and heredocs or
  here-strings fed to a shell, are scanned as commands. Git aliases are followed up to 5 levels, including aliases that
  start with options (`-c k=v push`); a `!` shell alias's text is scanned once (a nested shell alias that mentions push
  is unverifiable).
- **Unverifiable, so denied in block mode:** `$(…)`, backticks, process substitution, a here-string, `eval`, `xargs` or a
  shell function in a command that runs `git push` (or has the words `git` and `push`, counting inside substitutions);
  `--all`, `--mirror`, `--tags`, `--delete`, `--prune`, `-d`, `:dst` deletions and wildcard refspecs; a refspec source
  that doesn't resolve to a commit; `git -C`/`--git-dir` pointing at another repository or worktree; `--namespace` and
  `--config-env`; with no refspec, `push.default=matching` or any `remote.<remote>.push`; an unbalanced quote.
- **What is pushed:** no refspec → `HEAD` against `@{push}`, `@{upstream}`, then the resolved remote's default branch
  (`refs/remotes/<remote>/HEAD`, then `…/main`, then `…/master`). An explicit refspec → the source commit against
  `refs/remotes/<remote>/<dst>`, then the same default-branch refs (a new branch, as in `git push -u origin HEAD`, is
  checked for what it adds since its merge-base with the remote's default branch, even when `origin/HEAD` is unset). Each
  diff is `base...commit`, so it starts at the merge-base. No usable base → every gated file in the pushed commit's
  tree (`ls-tree -r`, so a committed file deleted only in the working tree is still checked). Paths are read
  NUL-separated with `core.quotePath=false`.
- **What counts as current:** the report's `status` is PASS, its `article_sha256` matches the bytes below, its
  `ruleset_version` is the installed ruleset's and its `profile_sha256` is the profile resolved as lint-watch resolves
  it (calibration notes included). A profile that can't be resolved makes the push unverifiable.
- **Which bytes are compared:** for `HEAD`, when `git diff --quiet HEAD -- <path>` says the working tree matches (after
  autocrlf, clean filters or LFS), the working-tree bytes the check read; otherwise the committed blob. A path absent
  from the pushed tree is a deletion and skipped; a path that's there but unreadable is unverifiable.
- **Not modelled (known gaps):** `cd` earlier in the same command (the gate checks the project directory; `-C` is resolved
  from the Bash tool's cwd); `GIT_DIR`, `GIT_CONFIG_*` and similar environment assignments; commands written to a shell's standard
  input (`git push` echoed into `sh`); `xargs git` reading the subcommand from stdin; scripts and Makefiles that push; remote-
  tracking refs mapped by a non-default `remote.<name>.fetch`; MCP publishing (out of scope for v0.1).

## 7. Skill listing and manual-only skills

Checked 2026-10-12, Claude Code CLI (same build as section 6). The Claude Code skills docs' invocation table says a
skill with `disable-model-invocation: true` has its description kept out of the model's context, and it is loaded only
when the user invokes it by name.

Scratch probe `/tmp/ps-probe3/plugin`: one skill with a 150-character description and `disable-model-invocation: true`.
`claude --plugin-dir . plugin details probe3` reported `Always-on: ~64 tok`, with the skill's own row at `~60` always-on
and `< 20` on-invoke. So `plugin details` counts manual-only skills in the always-on total even though the docs say
they aren't listed.

Decision: `scripts/dev/token_budget.py` subtracts the per-component cost of every skill with
`disable-model-invocation: true` and prints what it left out. Auto-trigger skills and agents still count in full, and
`tests/test_descriptions.py` caps every description either way.

## 8. SubagentStart and SessionStart hook input

Checked 2026-10-12 against the hooks reference (`https://code.claude.com/docs/en/hooks`).

- `SubagentStart` stdin carries `agent_id` and `agent_type`. `agent_type` is the field the brief hook reads; a plugin
  agent shows as `plainspoken:<name>`.
- `SubagentStart` can't block, but it accepts `hookSpecificOutput.additionalContext` (a string added to the subagent's
  context before its first prompt). So the brief is registered on both `SessionStart` and `SubagentStart`.
- `SessionStart` matchers: `startup`, `resume`, `clear`, `compact` (and `fork`, which the hook doesn't need). Its stdin
  also has `source` and an optional `agent_type` (set when the session itself runs as an agent); the hook skips any
  `plainspoken:*` type on both events.
- **Observed 2026-10-12 (live probe, Claude Code 2.1.296).** With `[brief] enabled = true` in a scratch project, a
  `check` run started four `plainspoken:tells-judge` subagents. A scratch copy of the hook logged each `SubagentStart`
  stdin: `agent_type` was exactly `plainspoken:tells-judge` (so the `plainspoken:` prefix test in
  `hooks/session_brief.py` is right), alongside `agent_id`, `session_id`, `prompt_id`, `cwd` and `transcript_path`.
  The hook emitted nothing for any of the four. The `SessionStart` event (`source: startup`) has no `agent_type`, and
  the hook emitted the brief for it. No code change was needed.

## 9. Kaizen hooks and permissions in `claude -p` (Phase 5 E2E)

Observed 2026-10-14 on Claude Code CLI 2.1.299, Linux, `claude -p --plugin-dir` on the subscription
(`docs/acceptance/p5-e2e.md`).

- **Which event counts a judge run.** A scratch copy of `hooks/kaizen_backstop.py` logged its stdin during a `check`
  run with 8 `plainspoken:tells-judge` runs (2 rounds × 4). **SubagentStop fired 8 times**, once per run, with
  `agent_type` exactly `plainspoken:tells-judge` and a distinct `agent_id` each time. Its stdin keys:
  `agent_id`, `agent_transcript_path`, `agent_type`, `background_tasks`, `cwd`, `effort`, `hook_event_name`,
  `last_assistant_message`, `permission_mode`, `prompt_id`, `session_crons`, `session_id`, `stop_hook_active`,
  `transcript_path`. **PostToolUse(SubagentHandback) never fired.** No subagent called a tool by that name: the
  judge's `tools: Read, Grep, Glob` don't include one, and it returns its reply as its final message. The friction
  file got 8 `agent_handback` lines, and `kaizen report` printed `judge replies returned (backstop) 8 vs recorded 8`.
- **SubagentStop carries the reply text.** `last_assistant_message` is the judge's whole reply, including evidence
  quotes from the article. The backstop reads only `agent_type` and `agent_id`. A hook that logs more must not store
  that field.
- **Stop `systemMessage` is visible in stream-json** as `{"type":"system","subtype":"informational","content":"Stop
  says: <message>","level":"notice"}`. Other hook events (only SessionStart shows up) appear as `hook_started` /
  `hook_response` system lines. PostToolUse, SubagentStop and Stop don't appear that way.
- **Skill `allowed-tools` apply in `-p` mode.** With no `--allowedTools`, `kaizen dismiss` and `kaizen decisions`
  (both in the kaizen skill's list) ran with no denial. A command outside the list is a **denial, not a prompt**:
  `kaizen calibrate` and `kaizen apply … --dry-run` each produced 2 `permission_denials`. The chained form gave `This
  Bash command contains multiple operations. The following part requires approval: …`, the plain form gave `This
  command requires approval`. A narrow `--allowedTools "Bash(python3 <plugin>/lib/run.py kaizen calibrate*)"` (or
  `…kaizen apply*`) let each one through.
- **Compound commands.** A command chained with `;` passes when every part is pre-approved (or is a read-only builtin
  like `echo`): `kaizen decisions; echo …; kaizen review; echo …` ran without a prompt. When one part isn't
  approved, the error names that part.

## 10. What the Phase 6 eval runs observed

Observed 2026-10-16 on Claude Code CLI 2.1.300, Linux, on the subscription (`docs/acceptance/p6-evals.md`).

- **`claude -p` reads the prompt on stdin.** With `--output-format json` the reply is one object. The keys the eval
  code reads: `result` (the reply text), `modelUsage` (one key, the model id that answered), `total_cost_usd`
  (notional on a subscription: what the tokens would cost on the API, nothing billed), `is_error`, `num_turns` and
  `permission_denials`.
- **Isolating a `--plugin-dir` run.** `--safe-mode` hides the `--plugin-dir` plugin's skills entirely, so it can't
  be used to test the plugin. `--setting-sources project,local` loads the `--plugin-dir` skills but none of the
  user's own plugins or skills, and not the user's CLAUDE.md. Probed with haiku: the session listed `plainspoken:*`
  skills and no user plugin's skills, and a reviewer confirmed the user CLAUDE.md wasn't loaded. The drafting
  harness (`scripts/dev/draft_runs.py`) runs every plugin arm this way.
- **The write skill's research gate stops a `-p` run.** When a brief asks for facts it doesn't carry, the `write`
  skill stops and says it won't fill them in from memory: 2 turns, about US$0.10 notional. The plain model, given
  the same brief, invents the facts. Ablation briefs must therefore carry every fact the draft needs.
- **A full `write` run costs about US$1.7 to 5.4 notional per draft on Opus**, including the check it runs (4
  judges per round). Most of that is the check.
- **OpenRouter's catalogue is free.** `GET https://openrouter.ai/api/v1/models` needs no key and lists every model's
  slug with its per-token prices (`pricing.prompt`, `pricing.completion`). On 2026-10-16 all six panel slugs then in
  `evals/panel.toml` resolved, and on 2026-10-17 all five of the revised panel's. `eval panel check` makes this one
  request. Privacy routing is per request: `provider.data_collection` ("allow" by default at OpenRouter; plainspoken
  sends "deny") and `provider.zdr` (zero-data-retention endpoints only), per openrouter.ai/docs provider routing,
  fetched 2026-10-17.
- **What a paid OpenRouter run showed (2026-10-17, a 1,130-call judge run, US$3.86):**
  - **An account-wide "ZDR only" setting wins.** The request's `data_collection` and `zdr` can't widen routing past
    it. A request that excludes every ZDR host gets HTTP 404, and the message names the account settings.
  - **`GET /api/v1/endpoints/zdr` is free.** It lists every zero-retention endpoint by model and host.
    `GET /api/v1/models/<slug>/endpoints` lists every host for one model.
  - **The completion response names the host that served it** (`provider`, e.g. `"Parasail"` for DeepSeek V4.1
    Flash on 2026-10-18). Since 2026-10-18 every reply records it (`Reply.provider`, optional in `replies.jsonl` so
    older run folders still read) and the judge report's Models table shows it as "served by". Calls already go
    out at `temperature: 0`, so a run-to-run flip that lines up with a host change points at the host, not the
    sampling.
  - **OpenAI's only zero-retention host is Azure.** Azure answers every JR prompt with a canned "I'm sorry, but I
    cannot assist with that request" and 0 tokens. The J prompts work. So under account ZDR, OpenAI judges J1–J4
    only (`groups` in the panel).
  - **Reasoning models can spend the whole reply budget thinking.** At 2,000 tokens, DeepSeek, Qwen and Muse
    Glimmer sometimes returned no answer (`finish_reason: length`). At 6,000, GLM-5.3 still did on 13 of 226 cases;
    a retry at 16,000 recovered most of them.
  - **Mistral Large 4's only zero-retention host rate-limited** 55 of 68 calls with HTTP 429, even at one call at a
    time.

## 11. Manual-only skills by permission rule, and plugin options on an installed copy

Probed 2026-10-19 on Claude Code CLI 2.1.303, Linux, `claude -p --model sonnet` on the subscription. Scratch project
under `/tmp` (`git init`, its own `.claude/settings.json`), with plainspoken 0.4.0 installed from its marketplace at
project scope (`claude plugin install plainspoken@<marketplace> --scope project`, so the cached copy, not
`--plugin-dir`). Every run used `--setting-sources project,local --output-format stream-json --verbose`; the
`--allowedTools` list came after the prompt. The scratch project and the project-scope install were removed after.

**Does `permissions.deny: ["Skill(plainspoken:write)"]` make the skill manual-only?** Yes, both halves.

- **A0, no deny.** `Draft a short blog post about why I prefer loose-leaf tea to tea bags, and save it to post.md.`
  Claude wrote the post itself, with no Skill call. This prompt doesn't trigger the skill on sonnet, so A0 tests
  nothing.
- **A1, no deny.** `Use the plainspoken write skill to draft a short blog post about …`. The model called
  `Skill {"skill": "plainspoken:write"}`, and the skill stopped at its research gate.
- **B1, deny.** The same prompt as A1. The same Skill call returned `Skill execution blocked by permission rules`,
  and `permission_denials` listed it.
- **B2, deny.** `/plainspoken:write a short blog post about …`. The skill ran (its research-gate reply), and
  `permission_denials` was empty.
- **B3, deny.** `/plainspoken:write Before doing anything else, quote verbatim the top-level heading …`. The reply
  quoted `# plainspoken write` and the skill's first core rule, so the slash command loaded the skill body.

So the deny rule stops the model's own Skill call, which is how a skill auto-triggers, and leaves the slash command
working. Not probed: an interactive session, and one skill starting a denied one (write starting check); the skills
read the other skill's file when they can't start it.

**Do `CLAUDE_PLUGIN_OPTION_*` values reach a hook on an installed copy?** Yes. `pluginConfigs` is read from user
(and managed) settings only (settings reference, fetched 2026-10-19: project and local entries are ignored), so the
probe set the option through `--settings '{"pluginConfigs":{"plainspoken@<marketplace>":{"options":{"targets":
["docs/**"]}}}}'` rather than the user's own settings file. Prompt (C1): write the same text with several tells to
`post.md` and to `docs/a.md`, run `env | grep -c CLAUDE_PLUGIN_OPTION || true` with Bash, and report any hook
feedback.

- The lint-watch hook linted `docs/a.md` (its PostToolUse context was the lint summary) and said nothing for
  `post.md`. Its state file held one slot, `<session>|docs/a.md`, and the project's ledger had `fired` events for
  one document. With no option the hook falls back to `**/*.md` and would have linted both, so
  `CLAUDE_PLUGIN_OPTION_TARGETS` reached the hook. Its encoding was one that `hooks/_common.py` `parse_targets`
  reads (a JSON array, or newline- or comma-separated); the raw value wasn't printed.
- The Bash tool saw none (`0`), as in section 4.
- Not observed: whether a value set only in the user's own settings file behaves the same (the docs say it does),
  and whether an unset option exports its manifest default.

Consequences: a host can make skills manual-only with the deny rule (README, Host setup), so there's no `[skills]`
config. Hooks still fall back to the manifest defaults, since a `--plugin-dir` session has no options (section 2),
and the project config (`[lint_watch] paths`, `[integrity] paths`, `[gate] strictness`) still beats the option.

## 12. Adapter assumptions checked against the live services

Checked 2026-10-19 on Linux. These aren't Claude Code facts, but the kaizen adapters rest on them.

**Trello marks an edited comment with `data.dateLastEdited`.** Probed through the Trello REST API (`/1`) with the
host's own credentials, on one throwaway card on the host's board, archived straight after. Two comments were posted
(`POST /cards/{id}/actions/comments`), the first was edited (`PUT /actions/{id}/text`, HTTP 200), and the card's
comments were read back the way the adapter reads them (`GET /cards/{id}/actions?filter=commentCard&limit=1000`):

- the edited comment's `data` held `dateLastEdited` (an ISO time three seconds after its `date`) next to `text`,
  `card`, `idCard`, `textData`, `board`, `list` and `idAuthor`;
- the unedited comment's `data` had no `dateLastEdited` key at all;
- both had `type: commentCard`, a `date` and the card under `data.card.id`, newest first.

So `adapters/trello.py` skipping a comment whose `data.dateLastEdited` is set (and failing closed when the frame is
missing) holds. Not checked: an edit made in the Trello web or mobile app rather than through the API, and a comment
edited back to its original text.

**`gh issue view --json comments` returns every comment.** Read in the source of gh 2.45.0 (the version on the host;
`pkg/cmd/issue/view/view.go` and `http.go` at tag `v2.45.0`): when `comments` is among the `--json` fields,
`findIssue` calls `preloadIssueComments`, which pages the GraphQL `comments(first: 100, after: $endCursor)`
connection until `hasNextPage` is false. There's no cap, so the github adapter needs no `gh api --paginate`. The
Context7 copy of the gh docs doesn't cover it (it documents the caps on `subIssues`, `blockedBy` and `blocking`
only). Also seen live: `gh issue view <n> --json body,comments` works, while a bare `gh issue view <n>` fails with
"Projects (classic) is being deprecated" (its default fields include `projectCards`). The adapter asks for
`body,comments` only, so it isn't affected. Not tested live: a thread of more than 100 comments.

## 13. Does an output style reach subagents?

Probed 2026-10-19 on Claude Code CLI 2.1.303, Linux, `claude -p` on the subscription, model Sonnet, with
`--setting-sources project --strict-mcp-config --output-format stream-json --verbose`. Scratch project
`/tmp/ps-os-probe/proj` (a `git init` folder) and scratch plugin `/tmp/ps-os-probe/plugin`; neither is committed.
Each style's body held a made-up "session codeword"; the subagent reported every codeword its own system prompt and
instructions stated (`SUB=…`), or `SUB=NONE`. The stream-json showed the Agent call's prompt, so a codeword passed
on by the main agent would have been visible.

| Run | Output style (`outputStyle` in the project's `.claude/settings.json`) | Main | Subagent |
|---|---|---|---|
| 1 | project style `probe-style` (`.claude/output-styles/`) | `HERON-5521` | `probe-agent`: `SUB=NONE` |
| 2 | plugin style `osprobe:plugstyle` (--plugin-dir), CLAUDE.md codeword | both | `probe-agent`: `SUB=OSPREY-1207` |
| 3 | as run 2 | (not asked) | `general-purpose`: `SUB=NONE` |

- The init line named the style (`output_style: probe-style`, then `osprobe:plugstyle`), and the main agent quoted
  its codeword, so the style was in force in `-p` mode. Each Agent call's prompt was exactly what the probe asked
  for and held no codeword.
- Run 2's control: the custom agent reported the `CLAUDE.md` codeword (`OSPREY-1207`), so it reads its own context,
  and not the plugin style's (`KESTREL-8830`). That string appeared nowhere in the subagent's part of the stream.
- Run 3 is weaker: `general-purpose` reported neither codeword, the `CLAUDE.md` one included, so it shows the style
  didn't reach it but gives no positive control.

Result: **an output style reaches the main conversation only, not subagents** (project and plugin styles alike), as
the README says. Not tested: an interactive session, `/output-style` chosen mid-session, and plugin agents
(`plainspoken:*`), which are subagents like the two tested.
