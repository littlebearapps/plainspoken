# Watch-outs

The patterns below stop a reader even when every word is plain. They're described by what they do, never as word
lists. Each entry says what the pattern does to the reader and how to fix it, with one invented example; every fact
in an "after" is in its "before", and a bracketed note marks a gap only the writer can fill. For sentence rhythm, see
`rhythm.md`. For words the reader wouldn't use, see `insider-terms.md`.

## Method leak

How the work is done appears before what the reader gets. Tool names, acronyms, internal product names used as bare
nouns, taxonomy codes and numbers that matter to the writer rather than the reader all push the benefit down the page.

The reader came for the result and hits the machinery first. Move method below the first statement of what they get,
or cut it. A number is fine when the reader would know what to expect from it ("$40 a month minimum") and lost when
it only proves effort ("a 98/100 audit score").

Before:

> Our Zephyr-based pipeline runs nightly ETL of your sales data into a columnar store, with p95 query latency under
> 300 ms.

After:

> Your sales data is updated every night, and 95 in 100 requests for it are answered in under 300 milliseconds.

## Naming the part before its job

A finding about a system, page or process opens with the technical name of the part, so the reader has to learn a
term before they know why it matters.

Explain it in the order the reader meets it: what the reader would see, what it's for, what's there now and why it
matters to the people it affects, then name the technical part if the reader will need the word to ask for a fix.
Skip any link in that chain the reader already has: the person who runs a form knows what it's for.

Before:

> The booking form's submit handler has no client-side validation, so malformed dates return a 500 error.

After:

> If someone types a date the booking form can't read, they get an error page. The form should check the date
> before it's sent, and right now nothing does. [Writer: say what this costs, such as bookings lost.] For whoever
> fixes it: there's no client-side validation, and the error is a 500.

## Overclaim

A verb that promises a result the writer can't control. The writer influences the outcome but doesn't decide it, so
the sentence has to say what the writer actually does.

A sceptical reader has heard the promise before and discounts the whole page; one who believes it feels let down
later. Soften the verb without losing plainness: say what you build, set up or make easier, and let the outcome stay
the reader's.

Before:

> Our weekly newsletter guarantees more bookings for your studio.

After:

> [Writer: say what you do for the studio's weekly newsletter (write it, send it, both), and what the reader can
> expect from it, or leave the outcome out.]

## Soft abstractions

Agency-deck language that sounds like benefit and names nothing: a verb that gestures at improvement, a noun that
could stand for any service. The test is whether the sentence could sit on a competitor's page unchanged.

Nothing in it can be pictured, so the reader remembers none of it. Replace it with the specific thing the reader
would see, do or stop doing.

Before:

> We help organisations get more out of their digital presence through a considered, joined-up approach.

After:

> [Writer: name the one thing the reader gets. For example, "I fix the three pages most visitors land on."]

When the source gives no concrete fact, leave the gap marked. A rewrite can't invent one.

## Familiar shorthand

An everyday word that sounds exact and hides its scope: "capacity", "implementation", "reporting", "support". The
reader knows each word, so nothing makes them stop, and two readers of the same sentence can come away picturing
quite different amounts of work.

Ask "what exactly?" of each one: capacity to do what, and reporting that answers which question. Swap the word for
the shortest concrete phrase the source supports, or mark a gap for the writer when it doesn't say. Never trade
precision for brevity: a shorter line that drops the scope has changed what it means.

Before:

> The library has limited capacity for school visits this term.

After:

> The library can take [Writer: how many school visits, how often and how many children each time] this term.

## Benefit mush

Copy that is nominally about the reader but stays generic. Adding more benefit doesn't fix it; adding specifics does.

To the reader, a generic line is filler. Say what the reader will know, have or be able to do, in terms they could
picture.

Before:

> Get clearer, smarter visibility into what matters for your business.

After:

> [Writer: what will the reader see, know or be able to do? Name it in terms they could picture.]

A rewrite can't supply the specific. It can only mark where it goes.

## Negative framing

Two forms. The first narrates what other providers do badly; the second gives a verdict on the reader's current
situation. Both lead with the absence of a pain instead of the gain.

A reader already burned by another provider doesn't need it pointed out, and being told their site or process is poor
puts them on the defensive. Describe your own way plainly and let them draw the contrast.

A short line that recognises the reader's own words is fine if it is a possibility they own ("if enquiries have gone
quiet") and turns straight to the gain. A deficit verdict about their current work is not.

The exception is a reader who asked for the assessment: a review, an audit, a reply to "what's wrong?". Then the
finding is what they came for. Say the problem plainly, about the work rather than the person, and don't soften it
into an after-state or leave it out.

Before:

> Unlike the usual firms, there are no handoffs. Your site is slow and out of date.

After:

> You deal with the same person from start to finish. [Writer: say what the reader's site will do for them, in
> place of the verdict on its current state.]

## Assumed goal

The writer states the reader's objective as fact when the source never gave it, and a reader with another aim stops
trusting advice that was built for someone else. When the source doesn't say what the reader wants, write the
consequence as a condition: "if the club wants more members, the sign-up form is the page to fix first."

## Audience-noun drift

Nouns that suit one audience used on a page that serves several. "Customers", "leads" and "sales" read as cold on a
page that also speaks to members, donors, parents or volunteers.

Readers notice when they weren't the person being written to. On shared pages use inclusive nouns (people getting in
touch, the people you want to hear from, sign-ups, registrations). Commercial nouns stay on pages that are only for
commercial readers.

Before:

> Capture more leads from every visitor to your club's website.

After:

> Make it easier for visitors to your club's website to get in touch.

## Sameness collapse

Several parts of one page open with the same move, so their first sentences could swap places without anyone
noticing. Each opening should belong to one section and no other.

When every card promises the same thing, none of them is memorable and the reader can't tell the options apart. The
check: read each opening sentence without its heading. If you can't say which section it describes, rewrite it around
what only that section does.

Before:

> Photos: stop guessing about your images. Video: stop guessing about your clips. Audio: stop guessing about your
> recordings.

After:

> Photos: [Writer: what the reader gets from the photo service]. Video: [Writer: what the reader gets from the video
> service]. Audio: [Writer: what the reader gets from the audio service].

## Defining by what it isn't

Explaining a service by contrast with something else instead of saying what it does for the reader.

The reader learns what to rule out and still doesn't know what they're getting. Say what it does, and draw any
distinction as the reader's situation rather than as a comparison.

The bad form usually leans on a "not X, but Y" construction, so it is described here instead of quoted. Suppose a
draft explains group coaching by saying it isn't one-to-one coaching. The fix keeps only what the draft says group
coaching is, such as the size of the group or what a session covers. If the draft gives neither, both become
writer gaps.

## Length signals

A label that tells the reader the page is long or heavy ("20 min read") before it tells them what they'll understand.

A reader short on time sees the number and leaves. Either drop the label or open with what the reader will know
afterwards.

Before:

> What is a domain name? (22 min read)

After:

> What a domain name is

## Claims that go stale

A fact about the market, a trend or a platform that is true today and wrong in a year: "more people are using X every
month", "most shoppers now do Y".

A reader who checks finds it out of date and stops trusting the rest. Prefer wording that lasts, or give the source
and date inline so it can be updated.

Before:

> More people than ever are using voice assistants to shop.

After:

> Some people use voice assistants to shop. [Writer: add the figure, who measured it and when, or leave it at this.]

## False reassurance

A line that is true in a narrow sense but suggests something the reader would be upset to discover.

The reader finds out later that the comfort was thinner than it sounded. Say what the reader still has to do or
watch, and drop words that imply certainty ("exactly", "always", "never") unless that's the fact.

Before:

> You only pay when someone clicks your ad.

After:

> You pay for each click. [Writer: say what makes a click worth paying for, and what happens to clicks that go
> nowhere.]

## Capacity-blindness

Copy that is plain and honest and still reads as one more thing for a busy reader to manage: reports to read, tools to
learn, decisions to make.

The reader already has a full day. Say plainly what they won't have to do, and keep that to what's true.

Before:

> You'll get a monthly dashboard and a list of settings to review.

After:

> You'll get a monthly dashboard and a list of settings to review. [Writer: say which of these the reader has to
> act on, and which you handle.]

## Fake closure

A case study or example that ends with a triumphant outcome and no loose ends.

Real work leaves something open, so a tidy ending reads as a sales pitch. Where the draft gives it, close on what is
still uncertain or ongoing, and say so.

Before:

> The cafe's online orders rose after the new menu went up, and everyone was delighted.

After:

> The cafe's online orders rose after the new menu went up. [Writer: how much, over what period, and what is still
> unknown, such as whether the rise lasted.]

## Every call to action leads to the same place

Two or three buttons with different promises ("Get a quote", "Book a call", "Start free") that all land on one
page. The reader clicks one and arrives somewhere that doesn't acknowledge what they expected.

The reader feels misled. The fix is not to hide the shared destination. Say on the landing page what the reader is
about to do and how each promise is kept, and give them the same plain answer however they arrived.

Before:

> Buttons: "Get a quote", "Book a call", "Try it free". All three open the booking calendar.

After:

> Buttons: "Get a quote", "Book a call", "Try it free". Landing text: "Pick a time. [Writer: say what happens on
> the call and how it covers the quote and the free trial.]"
