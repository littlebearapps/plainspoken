# Action modules

An action module is ordinary markdown wrapped in two HTML comments, `<!-- module:NAME -->` and
`<!-- /module:NAME -->`. The markers carry no meaning a reader needs: with them ignored (as every markdown renderer
ignores comments), the text reads the same. A site can style the modules later without the content changing.

There are three: `start-here`, `decision` and `action-plan`. They're optional. Use one when the contract's `type`
suits it, mostly `task`, `self_check` and `decision`, and never on history or commentary: an evidence-trail piece
uses prose and its sources.

`RUN reader-value modules 'FILE'` checks the markup and prints one finding per line, with the line number:

- every opening marker has a matching closing marker, and modules don't nest;
- the name is one of the three;
- at most one module per section;
- every jump link in a `start-here` module points at a heading that exists, by its `{#id}` or its slug;
- no H1 or H2 heading starts with a section number.

## start-here: an early summary that routes

Placed near the top, after any summary line. It gives the outcome, the effort, what to do first, what to leave for
later, how the reader knows they're done, and a link to the full plan.

```markdown
<!-- module:start-here -->
## Start here {#start-here}

**Outcome:** a cleared kitchen drain, or a clear sign it needs a plumber.
**Time:** about 30 minutes.

**Do first:** the trap under the sink. **Leave for later:** the outside drain.

**Done when:** a full sink empties in under a minute.

[Jump to the plan](#action-plan)
<!-- /module:start-here -->

<!-- module:action-plan -->
## Clear the drain {#action-plan}

### 1. Empty the trap {#task-trap}

Put a bucket under the trap, then unscrew the trap cap under the kitchen sink.

**Done when:** the water runs into the bucket. **Stop if:** the cap won't turn by hand.
<!-- /module:action-plan -->
```

The jump link's target has to exist in the same file. A link to `#action-plan` with no heading carrying that id or
slug is a finding.

## decision: prioritise or skip

A labelled comparison. The words carry the meaning: a site may colour the columns, but colour is never the only
signal.

```markdown
<!-- module:decision -->
## What I'd do first, and what can wait {#prioritise-skip}

| Do first | Can wait |
|---|---|
| Clean the sink trap | Buying a drain camera |
| Check the outside gully for leaves | Replacing the pipes |
| Note which fixtures drain slowly | Chemical cleaners |
<!-- /module:decision -->
```

## action-plan: numbered tasks

Each task can carry its order, the action (a verb, the thing it acts on, and where), its effort, what it needs, the
expected result, a "done when" signal, a "stop if" warning, and where doing it yourself ends. Give each task an H3
heading with its own `{#id}` so it can be linked to. Numbering H3 steps by hand is fine.

```markdown
<!-- module:action-plan -->
## Sharpen one chisel {#action-plan}

### 1. Check the edge {#task-check}

Hold the chisel under a bright light at the bench and look for chips and a rounded bevel.

**Needs:** a bright light. **Done when:** you know whether it needs honing or regrinding.
**Stop if:** there's a chip you can see. That's a regrind, not a hone.

### 2. Hone the bevel {#task-hone}

Set the chisel in the honing guide and push it along the coarse side of the stone.

**Done when:** a small burr forms along the whole back edge.
<!-- /module:action-plan -->
```

## Design rules

- One canonical source per action. The task lives in the body only; don't copy it into frontmatter or a second list.
- Stable ids. Give module headings an explicit `{#id}` so links and bookmarks survive a heading edit.
- Never write section numbers into H1 or H2 headings (`## 1. Clear the trap`). A site numbers sections when it
  renders them; a number in the source changes the slug, breaks every link to it, and needs renumbering whenever a
  section moves.
- One dominant module per section. A summary, a decision table, a plan and callouts all in one section compete.
- No advice in an image, and nothing important hidden behind an accordion. FAQ answers are the one exception, and
  only when the answers are in the page's text as served, not fetched by a script.
- Time and cost figures in a module are claims. "About 30 minutes" goes in the claim ledger, or comes out.

## What not to ship

- A start-here link to an id that doesn't exist.
- A task-type plan with steps but no "done when" or "stop if".
- A decision table whose only signal is colour.
- A history piece rewritten as numbered steps.
- A cost or time figure that isn't in the claim ledger.
