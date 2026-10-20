# The delivery gate

Deliver mode has the finished draft read against its contract by the isolated `delivery-checker`, which never wrote
it. The gate tests delivery, not counts: did the reader get what the contract promised? The reviewer's rubric is
`data/rubrics/delivery.md` in the plugin; the checklist below is the same seven items, by the names the reviewer and
`reader-value deliver` use.

## The checklist

Each item passes only on text in the draft, quoted verbatim. A failed item notes the line where it falls short, or
that the draft never gets to it.

1. **It delivers the promised outcome** (`outcome`). Read `promised_outcome`, then find where the draft gives the
   reader that outcome. A draft that circles the topic without getting there fails.
2. **At least one action or insight works without further research** (`standalone_action`). The reader can act on
   it, or use it to decide, from the draft alone. "Look into your options" fails; "remove the trap cap and check for
   a blockage" passes. Actions name a verb, the thing it acts on, and where.
3. **Access, effort and risk are disclosed** (`disclosure`). The tools, accounts, time and cost the reader needs,
   and what can go wrong, are stated where the reader needs them, not after the step. Every time or cost figure is
   a claim for the ledger. A draft that asks the reader to do nothing has nothing to disclose: the item is `n/a`.
4. **It has a success signal and a stop or skip boundary** (`success_and_stop`). The reader can tell it worked, and
   knows when to stop, skip the step or get help. A procedural piece with steps but no "done when" and no "stop if"
   fails.
5. **The advice isn't a disguised pitch** (`not_a_pitch`). The steps work for a reader who never buys anything.
   Advice that only makes sense with the author's service, or that withholds the useful part to sell it, fails.
   The CTA is never counted towards any item.
6. **The original value is real** (`original_value`). The method, data or experience named in `original_value` is
   in the draft as it stands, specifically enough to be recognised.
7. **A start-here summary matches what it routes to** (`start_here`). Where the draft has a start-here module, it
   routes to the full section with the same outcome and the same first step. With no start-here module, `n/a`.

Where the draft uses action modules, the module check must also print no findings. `reader-value deliver` runs it
and fails the gate on any finding.

**History and commentary: plainspoken's reading, not the ported text.** The gate this was ported from asks every
piece for a success signal and a stop or skip boundary (item 4). An `evidence_trail` or
`historical_interpretation` contract has no procedural fields, so plainspoken reads item 4 for those types as met
by the evidence trail: the draft shows where the reader can check the account or explore further, and where the
evidence runs out.

## Counts are never the gate

The number of tips, tools, callouts or resource links is a smell test at most. A draft that hits a count but doesn't
deliver its promised outcome fails. A draft that delivers with one clear decision table passes.

## Who decides

Only the isolated reviewer's recorded reply can pass the gate. When no subagent can run, the writer reads the draft
against this checklist and records the reading with `--reviewer self-check`. That record keeps the writer's FAIL,
and turns a PASS reading into INCOMPLETE: the producer never awards its own pass. `reader-value status` reads the
record back and says STALE once the draft, contract or rubric has changed since.

## When it fails

Fix the content or park the piece. Never weaken the contract to fit the draft: changing `promised_outcome` after
reading the draft turns the gate into a description of whatever was written. If the contract really was wrong (the
reader turned out to need something else), say so and go back to outline mode with the user's agreement.

## Example

The contract, for the invented draft `drafts/kitchen-sink.md`, saved at
`.plainspoken/reader-value/kitchen-sink.reader-value.toml` (the fields that matter here):

```toml
type = "task"
primary_reader = "A homeowner with a slow-draining kitchen sink"
promised_outcome = "A cleared drain, or a clear sign that it's a job for a licensed plumber"
effort = "about 30 minutes"
stop_condition = "Stop and call a licensed plumber if water backs up into another fixture"
```

The report deliver mode gives for a draft that falls short, with invented line numbers and key:

```text
reader-value: FAIL
Reviewer: the isolated delivery-checker, in a fresh context.
- outcome: pass (line 41, "refit the trap and run a full sink")
- standalone_action: pass (line 22, "remove the trap cap")
- disclosure: fail (line 22, no warning that the trap holds dirty water; put the bucket in before this step)
- success_and_stop: fail (no stop boundary anywhere; say when to call a plumber after line 44)
- not_a_pitch: pass (line 30, "you don't need any special tools")
- original_value: pass (line 12, "the three checks I run first")
- start_here: n/a (no start-here module)
Module findings:
line 9: module 'decision' is never closed (add <!-- /module:decision -->)
Claims to ledger:
- "about 30 minutes" (line 10): no ledger yet at .plainspoken/claims/kitchen-sink-3f9a1c2e.claims.toml
Record: .plainspoken/reports/kitchen-sink-3f9a1c2e.delivery.json
Contract: .plainspoken/reader-value/kitchen-sink.reader-value.toml
Checked against the contract only. You decide what to publish.
```
