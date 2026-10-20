# Worked examples

Every example here is invented: the businesses, people, dates and numbers are made up.

### Example 1: a council's bin-collection change notice

Reader: a resident who reads the council's mail between other things.

Before:

> Effective 4 November, kerbside organics (green-lid) and co-mingled recycling (yellow-lid) collection cycles will be
> realigned across Zone 3 following a contractor transition, moving from Tuesday to Thursday. Bin-out compliance
> windows are unchanged (6 am). Residents with an existing service-request ID should retain it.

After:

> **From 4 November your bins go out on a different day.**
> Green-lid and yellow-lid bins in your area will be collected on Thursdays instead of Tuesdays. Put them out by 6 am,
> as before. If you've already reported a problem, keep your reference number; it still works.

Caught by: zero-prior-knowledge (the opening never said what changes for the reader), insider terms ("co-mingled",
"cycles", "Zone 3", "bin-out compliance"), and actionability (nothing said what to do or when). Every fact in the
"after" is in the "before"; the rewrite only reshapes it.

### Example 2: a software release note for customers

Reader: someone who runs a small shop and uses the till software every day.

Before:

> v4.2 deprecates the legacy sync endpoint. Offline queues are now flushed on reconnect with idempotent retries, and
> the settings pane's tax-profile schema has been migrated. Users on v3 must upgrade before 1 December.

After:

> **Your till now catches up on its own after the internet drops.**
> Sales rung up while you're offline are sent through as soon as you're back online, and none are counted twice. Your
> tax settings have been moved across automatically. If you're still on version 3, update before 1 December.

Caught by: insider terms ("legacy sync endpoint", "idempotent retries", "schema"), the read-aloud test (a stack of
clauses with no person in them), and actionability (the one thing to do and its deadline were buried in the last
line).

### Example 3: a community choir's membership page

Reader: a retiree looking for something to do on weekday evenings, who has never sung in a group.

Before:

> Our forty-voice choir meets on Wednesday evenings. Membership is open to all vocal ranges (SATB) with no music
> reading required, subject to a brief voice placement with the choir leader on the first Wednesday evening, which is
> not an audition. Annual subscription is $120, or $80 concession, payable on enrolment. Repertoire spans the sacred
> and secular canon.

After:

> **Come and sing with us. You don't need to read music.**
> We're a choir of forty people and we meet on Wednesday evenings. On your first night the choir leader has a short
> chat with you to find the right group for your voice; it's not an audition. Joining costs $120 a year, or $80 on a
> concession. We sing everything from hymns to pop. [Check: does "hymns to pop" match the actual repertoire?]

Caught by: insider terms ("SATB", "voice placement", "repertoire", "canon"), and the zero-prior-knowledge test (the
page buried that beginners are welcome and what happens on a first night). The one bracket marks a gap: the "before"
said "sacred and secular", and "pop" is the writer's guess, so the writer has to confirm it or drop it.

### Example 4: a café's notice about new opening hours

Reader: a regular who walks past most mornings and glances at the door.

Before:

> Please be advised that from Monday our trading hours are subject to revision. Weekday service will commence at
> 7:30 and conclude at 2:00, with weekend hours to be confirmed. We thank you for your continued patronage.

After:

> **From Monday we open at 7:30 and close at 2:00 on weekdays.**
> Weekend hours are still to be confirmed. Thanks for coming in.

Caught by: the read-aloud test (nobody says "be advised" or "continued patronage" at the counter), and
writing about the writing (the first sentence announced a notice instead of saying the new times). The "after" keeps
the unknown as unknown. It says weekend hours aren't decided yet and doesn't invent them.
