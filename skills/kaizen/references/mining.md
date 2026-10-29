# Tell mining

Mining looks for phrases and habits that model drafts use far more often than people do. It compares drafts written
from fixed briefs with a human corpus the person supplies, and queues at most 5 model-tagged proposals. It never
calls a model itself, never edits the ruleset and never sends anything: mined proposals stay in the local queue.

1. **Write the drafts.** For each brief in `${CLAUDE_PLUGIN_ROOT}/evals/briefs/`, and each Claude model the person
   picks (default: the session's model), start one fresh subagent whose whole prompt is the brief's text verbatim,
   with no other instruction: no system note, no style advice, no hint about what the draft is for. The subagent
   uses no plainspoken skill. One brief, one model, one subagent. Mining needs at least 10 drafts per model and
   there are 6 briefs, so run every brief twice for each model, with a fresh subagent each time.
2. **Save each reply** unchanged as `.plainspoken/kaizen/mining/<YYYY-MM>/<model id>/<brief stem>.md` (the second
   run of a brief as `<brief stem>-2.md`): the month you ran it, the model's id (letters, digits, `.`, `_` and `-`
   only), and the brief's file name without `.md`. A model with fewer than 10 drafts is skipped.
3. **Mine.** `RUN kaizen mine --drafts .plainspoken/kaizen/mining/<YYYY-MM> --corpus <globs>`, where the globs are
   the person's own human-written files, relative to the project root. With `[kaizen] human_corpus` set in
   `.plainspoken/config.toml`, leave `--corpus` out. Ask the person for the corpus; never use model output or the
   drafts themselves as the human side. `--dry-run` shows the candidates and stores nothing. With `[kaizen]
   monthly_cap` set, mining keeps no more than what calibrate left of the cap this month; `--max N` lowers the
   limit for one run.
4. **Present the candidates** as printed: the model, the phrase or rule, the ratio and share, and the action. Each is
   stored as a proposal with its own `.md` file under `.plainspoken/kaizen/proposals/`. It's never sent to github or
   trello, whatever the adapter: the person decides it in that file, then you run `RUN kaizen decisions`.

Other vendors' models wait for the panel adapter (Phase 6): they need an API key and the owner's go-ahead. The drafts
folder is already laid out by model id, so their drafts slot in beside Claude's.
