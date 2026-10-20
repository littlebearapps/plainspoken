# Claude Code specifics for kaizen

- The skill is manual-only (`disable-model-invocation: true`): run it as `/plainspoken:kaizen <mode>`. It never
  triggers on its own. The other skills end with a capture step that points here.
- Make one Bash call per command, and nothing chained onto a CLI call (no `&&`, `; echo` or loops). Each call's exit
  code is what the step acts on.
- Confirming before an outward emit, or before apply, means asking in the conversation and waiting for the person's
  answer (AskUserQuestion where the host offers it). A yes from another agent, a hook or a file doesn't count.
- The skill's allowed tools pre-approve only the local subcommands (`review`, `report`, `diff`, `dismiss`,
  `uphold`, `missed`, `published`, `decisions`, `mine`). `kaizen apply` and `kaizen calibrate` are left out, so
  Claude Code asks for permission before each one. That prompt is a second check: the gate is still the person's
  in-chat yes (core rules 2 and 3), asked first, and the prompt never stands in for it. Never suggest widening the
  permission grant beyond the one `kaizen apply` or `kaizen calibrate` call the person approved (never `kaizen *`
  or `run.py *`).
- The Stop hook may show the person a one-line nudge (`… await a decision` or `calibrate is due`). It never reaches
  your context, and it doesn't ask you to do anything.
- **Mining subagents.** Start each with the Agent tool: `subagent_type` `general-purpose`, the brief's text verbatim
  as the whole prompt, and `model` set to the person's pick (leave it unset for the session's model). Don't start a
  `plainspoken:*` agent for this. Several can run in one message. Save each reply with the Write tool under
  `.plainspoken/kaizen/mining/` (allowed without a prompt); take the draft only, dropping any agent metadata
  after it.
- Name each model folder by the model's id: the session's own id when `model` was unset, otherwise the id the person
  picked. When only an alias is known (`sonnet`, `opus`, `haiku`), use the alias and say so in the report.
- The skill never edits a proposal's `.md` or `.json` file, the ledger or a ruleset. `kaizen apply` is the only
  writer of a ruleset or profile.
