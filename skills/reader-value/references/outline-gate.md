# The outline gate

Complete the contract honestly before drafting. The gate isn't a form to get through: if a field can only be filled
with something untrue, vague or a sales step, the honest answer is that the piece shouldn't be written yet.

## What the outline must answer

- **The reader's problem or decision**, in their words. "A homeowner whose kitchen sink drains slowly", not "people
  interested in plumbing".
- **The promised outcome**: what they can do, know or decide afterwards. An action or a decision, not a feeling.
- **The first useful action or insight**, the one the reader can use without further research. For a procedural
  piece, a verb, the thing it acts on, and where.
- **Effort, access and prerequisites**: how long it takes, what tools or accounts it needs, what it costs. Each
  figure is a claim for the ledger.
- **A success signal**: how the reader knows it worked.
- **A stop or skip boundary**: when to stop, skip the step, or get help. A piece about clearing a drain says when
  it's a job for a licensed plumber.
- **The original contribution**: the method, data or first-hand experience only this author brings.
- **The factual premises** the piece rests on. Each goes in the claim ledger.
- **A suitable action module**, if any (see [action-modules.md](action-modules.md)).

## What counts as value

Value depends on the kind of piece:

- **Practical guide:** a self-check, a prioritised plan, money not spent, a clear decision, an honest point to get
  help. Usual `type`: `task`, `decision`, `self_check`.
- **Technical post:** a command that runs, a build the reader can reproduce, a debugging path, the expected output,
  a trade-off. Usual `type`: `implementation`, `debugging_path`, `task`.
- **History or commentary:** an evidence trail, a timeline, places or questions to explore, competing readings.
  Usual `type`: `evidence_trail`, `historical_interpretation`.

A reflective history piece passes on its evidence trail. Don't turn it into "seven steps to appreciate the old hall".

## Park it

Report `reader-value outline: PARKED` and say why when:

- a required field can't be filled honestly;
- the promised outcome is really a sales step, or the only first action is getting in contact with the author;
- the piece exists mainly because the topic has search volume, a competitor covers it, a tool suggested it, it can
  target a keyword, or it gives the CTA somewhere to sit.

A parked topic isn't a failure. Some come back with a real reader once the author has the experience or data to
offer. Leave the contract on file with the reason.

## Two invented examples

Acme Plumbing wants a post on "best drain cleaners" because a competitor ranks for it. The only original value
anyone can name is a list the competitor already has, and the promised outcome comes down to booking an Acme Drain
Service. PARKED: it exists for a competitor's coverage and a CTA.

The same business writes "Is my toilet leaking into the bowl?" for a renter whose water bill jumped. The first
action is adding a few drops of food colouring to the cistern, the success signal is a bowl that's still clear after
15 minutes, and the stop boundary is colour in the bowl or water on the floor: that's a job for the landlord's
plumber. READY.
