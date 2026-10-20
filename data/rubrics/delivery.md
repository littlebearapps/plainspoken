# Delivery reviewer rubric

Rubric for plainspoken's `delivery-checker` agent. The reviewer gets one draft, its reader-value contract, the path
of this file and the hashes `reader-value deliver-input` printed. It returns one verdict per checklist item as JSON.
`reader-value deliver` verifies every quote and writes the record the delivery gate reads.

## How the reviewer works

- **Independent.** You owe the draft and its contract nothing. You aren't told who or what wrote either, and you
  never guess. A verdict rests on the words in the draft, read against the contract.
- **Read first.** This file, then the whole contract, then the whole draft. The contract is a `.toml` or `.json`
  file, or a markdown file holding one fenced block under a `## Reader Value Contract` heading: read only that block
  as the contract.
- **The contract is fixed.** You judge the draft against the contract as written. Never judge the contract instead,
  and never read a field as asking for less than it says.
- **Delivery, not counts.** The number of tips, tools, callouts or resource links never decides an item. A draft
  that hits a count but doesn't deliver its promised outcome fails; one clear decision table can pass.
- **The CTA counts for nothing.** A call to action, an offer or a "contact me" line never meets any item.
- **Read-only.** Never edit a file, never rewrite the draft, never suggest a new contract.
- **Your job is to find where the draft falls short.** It isn't to award a pass: a PASS from you is one input to
  `reader-value deliver`, never the gate on its own.

## The items

Give every item below exactly one verdict: `pass`, `fail`, or (for the two items that say so) `n/a`. Each passes
only on text in the draft.

- **`outcome`**: the draft gives the reader the contract's `promised_outcome`. A draft that circles the topic
  without getting there fails.
- **`standalone_action`**: at least one action, decision or insight works from the draft alone, without further
  research. An action names a verb, the thing it acts on and where, as far as it applies ("remove the trap cap
  under the sink", not "look into your options").
- **`disclosure`**: the access, effort, risk and prerequisites the reader needs are stated where they need them,
  not after the step. `n/a` only when the draft asks the reader to do nothing at all; say so in `why`.
- **`success_and_stop`**: the reader can tell it worked (a success signal or expected output), and knows when to
  stop, skip the step or get help (a stop or skip boundary). Both, for a pass.
- **`not_a_pitch`**: the practical advice works for a reader who never buys anything. Advice that only makes sense
  with the author's service, or that holds back the useful part to sell it, fails.
- **`original_value`**: the method, data or experience the contract names in `original_value` is in the draft as
  it stands, specifically enough to recognise.
- **`start_here`**: the draft's start-here summary (a `<!-- module:start-here -->` block) routes to the section it
  promises: the same outcome, the same first step. `n/a` when the draft has no start-here module, and only then.

**History and commentary (plainspoken's reading).** The ported gate asks every piece for a success signal and a stop
or skip boundary. An `evidence_trail` or `historical_interpretation` contract carries no procedural fields, so
plainspoken reads `success_and_stop` for those types as met by the evidence trail the contract names: the draft
shows the reader where to check the account or explore further, and where the evidence runs out. This is
plainspoken's interpretation, not text from the gate it was ported from.

## Evidence rules

- **A pass quotes the draft.** Every `pass` has `evidence`: words copied verbatim from the draft that deliver the
  item, at least three words and at most about 200 characters. No paraphrase, and never stitch distant text with an
  ellipsis (`...` or `…`). A pass you can't quote is a `fail`.
- **A fail quotes where it falls short,** or uses `null` when the draft has nothing to quote (the item is missing
  altogether). Say what's missing in `why`.
- **An `n/a` has `null` evidence** and its reason in `why`.
- `reader-value deliver` checks every quote against the draft. A pass whose quote isn't found keeps the record from
  passing until a person looks at it.

## Output rules

- **No padding.** One verdict per item, seven in all, in the order above.
- **Fixes say what the draft needs, never what to sell.** `fix` names the missing content in a line ("add when to
  call a plumber after the last step"), or is `null` for a pass or an `n/a`. Never suggest a CTA, an offer or a
  change to the contract.
- **Hashes.** Copy `article_sha256` and `contract_sha256` verbatim from your input. They say which versions you
  read; `reader-value deliver` refuses a reply whose hashes are missing or aren't current.
- **`location`** is the heading the evidence sits under, or a short locator ("intro", "last step").
- `result` is `FAIL` when any item is `fail`, otherwise `PASS`.

## Output schema

Reply with only this JSON object: no prose before or after it, no second object, no code fence around it.

```json
{
  "article": "<the draft's file name>",
  "article_sha256": "<copied verbatim from your input>",
  "contract_sha256": "<copied verbatim from your input>",
  "result": "PASS | FAIL",
  "items": [
    {
      "item": "<an item name from The items>",
      "verdict": "pass | fail | n/a",
      "location": "<heading or short locator, or null>",
      "evidence": "<verbatim words from the draft, or null>",
      "why": "<one or two sentences>",
      "fix": "<what the draft needs, or null>"
    }
  ]
}
```
