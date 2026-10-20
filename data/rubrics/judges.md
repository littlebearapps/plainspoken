# Judge rubric

Judge rubric for plainspoken's tells-judge. Each judge gets one group (J1–J4) or JR, an article path, the rule ids to decide, lint candidates, and the paths of this file and (optionally) the voice profile's calibration notes. Severity for every rule comes from the input's `severities` map (taken from `data/rules.toml`), except where an entry below sets it.

## How every judge works

- **Read first.** The article at the given path (all of it), and this file's entry for each rule you were given.
- **Calibration.** When the prompt gives `calibration_notes`, read that file and apply it as the voice's own allowances; it can relax or tighten what counts as a fail for this voice. Without it, judge by this rubric alone.
- **Decide exactly the rule ids in your `rules` list.** The orchestrator passes only your group's rules that apply to this article's profile. One verdict per listed id, no others, even if another rule's problem is obvious.
- **Verdicts are binary.** `pass` or `fail`, per the **Fail when** / **Pass when** lines below. When
  neither line clearly applies, it's a `pass`: a fail needs evidence you can quote.
- **Evidence.** A `fail` needs at least one evidence item: `line` (the 1-based line number in the file,
  as the Read tool numbers it), `quote` (the article's exact words, copied, at most 200 characters, and
  present verbatim on that line) and `reason` (one sentence). A `pass` has an empty evidence list.
- **Candidates.** The lint's CANDIDATE findings for your rules arrive as `{rule, severity, line,
  excerpt, message}`; `line: 0` means the whole article. A candidate is a lead, not a verdict: confirm or
  reject each one, then read the whole article for misses the lint's phrase lists and patterns can't
  see. A rule with no candidates still gets a verdict. Lint BLOCK and WARN findings aren't sent to you
  and stand on their own; don't re-decide them.
- **What counts as article text.** The body, plus the frontmatter keys listed in `visible_frontmatter_keys`, plus the `question`/`answer` items under `faq_frontmatter_key` when it is set. Fenced code, inline code, HTML comments, URLs, image paths and link targets are not prose.
- **Quotations are never a fail.** Words inside a verbatim third-party quotation (a straight
  double-quoted span of 4+ words, or a blockquote ending with an attribution `— Name` / `- Name`) are
  never evidence, whatever they contain.
- **Allow-markers.** `<!-- anti-ai-allow: <rule-id> "<exact phrase>" <reason> -->` on the line before
  (or on the same line) means that phrase on that line is not evidence for that rule.
- **Severity.** Copy each verdict's `severity` from the rubric entry; where the entry doesn't set it,
  use the severity given for the rule in your input's `severities` (the same value for `pass` and
  `fail`). Only 5e, 19 and 22 set it: their entries below say when the severity is `BLOCK` and when
  it's `WARN`, and the merge honours a judge's `BLOCK` for those three rules only.
- **Read-only.** Never edit a file, never rewrite the article, never suggest a fix. Fixing is a later
  step with its own rules.

**The deletion test.** Before you fail a phrase, delete it in your head. If the sentence loses nothing a reader needs, it is a tell; if it loses meaning, it is doing work, so pass it.

**Ineffective indicators.** These are not evidence on their own: correct grammar, a formal register, transition words, or a long word. Fail only on the patterns the rule names. (Source: Wikipedia, "Signs of AI writing", section "Ineffective indicators", oldid 1379367647, paraphrased.)

**Judge the text, not its origin.** You are never told who or what wrote the article, and you never guess who or what wrote it. A verdict rests on the words on the page.

## J1 Framing and meta

### 5b Meta-commentary
**Fail when** a sentence describes what the article is about to say, just said, or is doing, and carries
no content of its own. That includes frames the phrase list misses ("This is where…", "Here's what that
means…", "Now for the important part") when they only frame.
**Pass when** every such sentence also says something: "Here's what I found: the cache never expired" is
content, not a frame.
**Candidates:** phrase-list hits (`meta_commentary`). Reject a hit that's inside a real statement of
fact or a quotation; confirm one that only frames.

### 5d Scope disclaimers
**Fail when** a sentence pre-emptively disclaims the article's own completeness ("This isn't an
exhaustive list", "I'm oversimplifying here", "There are, of course, caveats").
**Pass when** each caveat is a concrete fact about scope ("This doesn't cover Shopify", "I haven't
tested this on Windows"). Hedges that the voice's calibration notes require on a claim are not
disclaimers.
**Candidates:** phrase-list hits (`scope_disclaimers`). Confirm when the sentence disclaims the article
in general; reject when it names the specific thing left out.

### 11 Unsolicited summary
**Fail when** the article ends with a summary block or sign-off: "In conclusion", "To sum up", "Key
takeaways" used as a recap of what was just said, "Hope this helps", "The bottom line is" followed by a
restatement.
**Pass when** the article just stops, or ends on something new. A section whose heading matches the profile's resource-list headings, an FAQ, or a TL;DR at the top is not an unsolicited summary.
**Candidates:** marker hits (`conclusion_markers`). Reject a marker that isn't in the closing stretch or
that introduces new material; confirm one that opens a recap.

### 18 Conclusion recycling
**Fail when** the final section (the last H2 before any section whose heading matches the profile's
resource-list headings, an FAQ or a CTA block) restates
the intro's argument without adding anything new: no new fact, step, question, decision or example. The
tell is restate + summarise ("Ultimately…", "In the end…") + a broad-implications gesture ("This matters
because…").
**Pass when** the last section adds at least one thing the reader didn't have before it.
**Candidates:** none (judge-only). Read the intro and the final section side by side; quote the
recycled sentence.

### 26 Announcement openers
**Fail when** a sentence opens with an emphasis announcement ("Importantly,", "Crucially,",
"Critically,") or a list preface ("Here are the top 5…", "Below are some key…") that could be deleted
with no loss of meaning.
**Pass when** the word is used literally ("Critically ill patients…") or the sentence says something
beyond announcing what comes next.
**Candidates:** opener hits (`announcement_openers`, `announcement_patterns`). Confirm when deleting the
opener loses nothing.

## J2 Structure and rhythm

### 6 Rule of three
**Fail when** three-item lists and series are the article's default shape: 3 or more *padded* triplets
(bullet lists or in-sentence series) where the third item is filler, a near-synonym of the other two, or the
count looks arbitrary, and triplets clearly outnumber lists of two, four or more.
**Padded means the delete test fails:** drop the third item and ask what the reader loses. Nothing, or only a
rephrase of the first two → padded. A distinct fact, a consequence or a different kind of point → load-bearing,
and that triplet doesn't count toward a fail, however many triplets the article has. Example: "The baths guide is longer, more specific, and gives swimmers more to work with." is
load-bearing: the third item is the consequence of the first two, and cutting it loses the point.
**Pass when** list lengths vary, the triplets are the real count (three repos, three steps that exist), or the
triplets are load-bearing. One natural triplet always passes. If load-bearing triplets are so frequent the
rhythm drums, say so in `reason` on a pass; that's for the reviewer, not a fail.
**Candidates:** only emitted when triplets run at `triplets_per_1000w_candidate` or more per 1,000
words, so no candidates doesn't mean no triplets. Confirm a candidate when its third item is padding.

### 7b Press-release opener
**Fail when** the article's first prose sentence is an announcement: "[past-tense verb] [number]
[things] across/in [number] [things]" ("Shipped 3 releases in one day", "Found 22 bugs across 3 tools")
or reads like a product-update email.
**Pass when** it opens on an observation, a scene, a question or a lesson.
**Candidates:** the first sentence, if it matched the announcement pattern. Also read the first sentence
yourself when there's no candidate.

### 7c Parallel constructions
**Fail when** 3+ consecutive sentences share the same grammatical shape for rhetorical effect ("Tests
check X. Dogfooding checks Y. Users check Z."), or on any negative parallelism: "not just X, it's Y",
"not only X but also Y", "it's not X, it's Y".
**Pass when** repeated shapes are incidental (a numbered procedure, a table converted to prose that the
reader needs in that order) or broken up by a question, fragment or aside.
**Candidates:** "not just / not only / not merely" hits. Confirm the rhetorical ones; read for
same-shape runs, which the lint can't see.

### 12 Compulsive balance / rhetorical questions
**Fail when** a "While X, Y" construction's X adds nothing and the sentence works as Y alone; on "on one
hand… on the other", "good arguments on both sides" where the article should pick a side; or on a
self-posed rhetorical question used for fake drama ("The result? …", "Why does this matter? Because…").
**Pass when** the trade-off is real and the article still states its position, or the question is one
the reader would actually ask (an FAQ question, a heading).
**Candidates:** `balance_patterns` and `rhetorical_question` hits. Reject a "while" that means "during"
or introduces a real concession the article then answers.

### 16 From X to Y ranges
**Fail when** "from X to Y" gestures at a vague span instead of naming the real things ("from content
creation to data analysis", "from small businesses to enterprise").
**Pass when** it's a real numeric, time, place or step range ("from 2.4 s to 1.1 s", "from Carlton to
Coburg", "from the login page to the checkout").
**Candidates:** "from … to …" hits (numeric ranges are already filtered out). Confirm the gestures.

### 21 Synonym cycling
**Fail when** one subject is renamed across nearby sentences for variety ("the tool… the platform… the
solution… the system") where a human would repeat the name or use a pronoun.
**Pass when** each name is the natural one, or the different names mean different things.
**Candidates:** none (judge-only). Quote the sentence with the second or third rename.

### 22 Challenges / Future outlook
**Fail when** a "Challenges" / "Future outlook" / "Looking ahead" / "Future prospects" section (or a
closing passage of the same shape) is generic: no dated, specific, sourced facts, just outline-shaped
filler.
**Pass when** the section is built from specific, dated, sourced facts, or there's no such section.
**Severity:** `BLOCK` only when the verbatim skeleton appears ("Despite its X, [subject] faces several
challenges…" / "Despite these challenges, [subject] continues to thrive"). Anything else that fails
(a reworded skeleton, generic Challenges / Future-outlook content) is `WARN`.
**Candidates:** headings that name a challenges / outlook section. The lint reports an exact skeleton
match as its own BLOCK; you decide whether the section content is generic.

## J3 Register and claims

### 2 Hard-ban vocabulary (qualified words and quoted mentions)
**Fail when** a qualified word is used in its banned sense: landscape / ecosystem / framework / navigate
/ unlock metaphorically, underscore / leverage / showcase as verbs, enduring figuratively ("the SEO
landscape", "navigate the changes", "unlock growth", "leverage your data").
**Pass when** the use is literal or a real technical term ("the npm ecosystem" as a package-registry
context, "the Astro framework", "navigate to Settings", "unlock the door", "leverage" as a finance noun).
The literal hard-ban words are the lint's call (BLOCK); don't re-decide them.
**Quoted ban-list word** (message "quoted on its own"): pass only when it's a genuine mention, the word
discussed as a word ("avoid words like 'robust'", `No "innovative."`); fail a scare-quoted use ("a
'robust' system").
**Candidates:** every hit on `ban_qualified` (landscape, ecosystem, framework, navigate, unlock,
underscore, leverage, showcase, enduring) and their inflections, plus any ban-list word quoted on its
own. Decide each one.

### 5c Copula avoidance
**Fail when** "serves as / stands as / functions as / acts as / represents / offers / features / boasts
/ marks" stands in for is / are / has ("The SDK serves as the main interface", "The page boasts a
contact form").
**Pass when** the verb carries its real meaning: a real offering ("The plan offers three tiers"), a real
feature list, a real representation ("each dot represents one session"), a real mark.
**Candidates:** every copula-list hit (`copula_candidates`). Test each by swapping in is / has: if
nothing is lost, confirm.

### 10 Hedging everything
**Fail when** the article dodges opinions it should hold: 3 or more hedges on the article's own
recommendations or conclusions ("it depends", "results may vary", "tends to be the preferred option in
many contexts") where the author has the evidence to commit.
**Pass when** the article commits to its recommendations. Hedges that the voice's calibration notes require (for example, a claims policy that asks for "usually" on contested points) are not a fail.
**Candidates:** `hedges` phrase hits. Reject the required and the factual ("it depends on your CMS,
and here's how to check"); count the rest.

### 12b Ghost citations
**Fail when** a claim is attributed to an unnamed source ("Studies show…", "Research has found…",
"Experts agree…") and neither that sentence nor the next names the source or links it.
**Pass when** the source is named or linked in the sentence or the next one.
**Candidates:** `ghost_citations` phrase hits. Check the sentence and the next for a named source or a
link before confirming.

### 12c Stakes inflation
**Fail when** something ordinary is framed as era-defining ("will define the next era", "reflects a
fundamental shift", "has far-reaching implications") beyond what the article's own evidence supports.
**Pass when** the stated scale matches the evidence in the article.
**Scope test:** judge the scale against the scope the sentence itself states. "For the whole sector" needs
sector-wide evidence; "for this street" needs only the street. When the article's evidence covers the scope the
sentence claims, it's a pass, even for a phrase on the candidate list.
**Size test:** a narrow scope doesn't excuse an inflated size. When the sentence calls the effect large,
wide-reaching or significant, the evidence has to show that size inside the named scope: the change reaches across
much of the one school, shop or event (many of its people, parts or routines). Big language about one local thing,
backed by one or two small changes, is a fail even though the scope is narrow.
**Candidates:** `stakes_inflation` phrase hits. Also read for inflated framing the list doesn't name.

### 17 Patronising analogies
**Fail when** an analogy talks down to a reader who doesn't need it ("Think of it as a highway for
data", "It's like a digital filing cabinet"), or analogies pile up where a direct explanation would do.
**Pass when** a single analogy genuinely helps the intended reader. How much analogy a reader needs depends on the reader; the calibration notes may set the bar. Without notes, fail only analogies that explain what the reader plainly already knows.
**What the reader already knows** comes from the passage itself. When the same text expects the reader to carry
out the thing (run the commands, lodge the form, reconcile the account), an analogy for its basics talks down to
them. When the text says its reader is new to it, a plain analogy can genuinely help.
**Candidates:** none (judge-only). Look for "think of it as", "it's like", "imagine".

### 27 Marketing-register optimise
**Fail when** optimise / optimize / optimisation is marketing register ("optimise your engagement /
presence / content / strategy").
**Pass when** the use is technical (image optimisation, query optimisation, Core Web Vitals, performance
optimisation, bid optimisation as a platform setting), or when the word is someone else's and the writer keeps
their distance: it's put in a vendor's or another person's mouth ("the brochure promises", "is supposed to") and
the text then doubts, tests or deflates the claim ("…to optimise your reach. Three months on, our reach is where
it was."). Judge the writer's own register, not the word.
**Still fail** when the phrase is the writer's paraphrase (indirect speech: "he wanted to know how to optimise
his funnel") or when the writer reports it and carries on in the same frame. Attribution alone isn't distance,
and giving a concrete answer to the question doesn't count as doubting the claim.
**Candidates:** every `optimise_forms` hit. Decide each one.

## J4 Sentence mechanics and narrative calibration

### 5e -ing sentence openers
**Confirm each opener first:** a participial phrase opening the sentence counts ("Building on this, the
SDK…", "Giving users live data, the page…"); a gerund subject doesn't ("Building a site takes time" —
the -ing word is the subject). Sentences inside quotations, bullets and tables don't count.
**Fail when** a section (everything under one H2; the intro before the first H2 is its own section) has
`ing_opener_section_warn` or more confirmed openers, or `ing_opener_consecutive_block` or more confirmed
openers in a row (for both values, see data/rules.toml `thresholds`).
**Pass when** neither count is reached after rejecting the gerund subjects.
**Severity:** `BLOCK` when `ing_opener_consecutive_block` or more confirmed openers are consecutive;
`WARN` when only the per-section count is reached.
**Candidates:** a section-level candidate (line = the section heading) when the raw count reaches the
threshold, and a sentence-level one at the third consecutive raw opener. Re-count with gerunds removed.

### 9 Zero informality
**Fail when** the whole article has no informal register at all: uniformly polished prose with no
contractions, fragments, And / But starters, asides or casual connectives, so it reads like a corporate
FAQ rather than a person. Quote the most representative over-polished sentence.
**Pass when** the voice shows a person anywhere in the article. Don't count markers mechanically (the
lint's HM rule does that); judge the register.
**Candidates:** none (judge-only).

### 19 Trailing -ing fake depth
**Confirm each clause first:** a trailing "-ing" clause tacked on to add fake analysis ("…, highlighting
the importance of observability", "…, ensuring a seamless experience") counts; one that states a real,
specific consequence with its own subject matter ("…, creating a second invoice for every order")
doesn't.
**Fail when** one section (everything under one H2) has `trailing_ing_section_block` or more confirmed
fake-depth clauses (for the value, see data/rules.toml `thresholds`).
**Pass when** no section reaches that count. A single decorative clause in a section passes.
**Severity:** `BLOCK` on every fail (the count above is the BLOCK line).
**Candidates:** trailing-clause hits on `trailing_ing_verbs`. Confirm or reject each, then count per
section; read for trailing clauses on verbs the list doesn't have.

### NR-3 Proper-noun density in narrative
Applies only when the profile has the `narrative` flag (the rule isn't sent otherwise).
**Fail when** a paragraph is a bare list of names, dates and places with no narrative glue (no
beginning, middle and end) AND no sensory detail.
**Pass when** dense proper nouns carry a compressed narrative ("Marla Voss opened the Ketterby baths in 1931. Tomas Reek took over in 1948... Between them, they kept the pool open through three floods") or sit among paragraphs with sensory texture.
**Candidates:** none (judge-only).

### NR-4 Long sentences protected in narrative
Applies only when the profile has the `narrative` flag (the rule isn't sent otherwise).
**Pass by default.** Long "and"-chained sentences are protected run-on enthusiasm when they're emotional
or narrative and surrounded by shorter sentences ("The baths were cold and loud and smelled of chlorine and wet wool, and every Saturday the whole town seemed to be in them").
**Fail only when** 4+ long "and"-chained sentences run in a row, or the long sentences are expository
(explaining, listing facts) rather than emotional or narrative. This verdict doesn't change the lint's
rule 7 / 7d findings.
**Candidates:** none (judge-only).

### NR-6 Opinion delivery in narrative
Applies only when the profile has the `narrative` flag (the rule isn't sent otherwise).
**Fail when** no blunt, first-person, declarative take sits within 3 sentences of an opinion marker ("I
think", "I reckon", "I guess", "to me", "anyway", "that's how I see it") anywhere in the article,
including when there's no marker at all. Quote the marker sentence that has no real take, or (with no
marker) the sentence where the article most clearly withholds one.
**Pass when** at least one real opinion is delivered that way ("I think the council was wrong to close the baths. The roof was the only part that needed fixing"), or the calibration notes exempt analysis pieces and this is one.
**Candidates:** one whole-article candidate (`line: 0`) when a marker is present. Find the marker and
check what's around it.

## JR Justification review

Fix or justify. A WARN
rule that still fails after the fix pass stays in the article only with a justification you accept. You review
justifications; you don't re-judge the rules, and you never edit anything.

**Input** (from `python3 -m plainspoken justify <article> --review-input`): `article`, `article_sha256`,
`justify_sha256`, and `items`, each `{rule, kind, reason, evidence}`. `evidence` is the failing rule's judge
evidence or its lint WARN findings (`line: 0` = the whole article).

**Read first:** the whole article; each item's rule entry in this file (its J-group
entry above, if it has one); and, for `voice`, the calibration notes if given.

**Accept when** all three hold: the reason is true of **every** evidence item for that rule; it's specific to
this article (it says what the text is doing, not that it "reads fine"); and the kind fits:
- `voice`: the pattern is something the voice's calibration notes ask for; name the section in your reason.
- `quote`: the evidence sits inside verbatim third-party text.
- `load_bearing`: removing or reshaping it would lose information the reader needs (e.g. the three items are
  the three real options).
- `false_positive`: the rule's own text (the entry above) says this isn't a hit.
- `format`: a structural element (FAQ, table, checklist, numbered steps) where the rule's pattern is the format
  itself.
- `metric`: an article-level metric (12f vocabulary variety, opener share or paragraph spread; 7; 12d) where the
  reason says why a removal-only fix pass can't move it honestly.

**Reject when** the reason is generic ("reads naturally", "stylistic choice"), covers only some of the evidence,
contradicts the rule's entry, or excuses exactly what the rule exists to catch (e.g. `voice` for a
phrase on a ban or WARN list). **When unsure, reject:** a rejection costs one small fix; a wrong accept puts a
tell in a published article.

**Reply with ONLY this JSON** (no prose, no code fence), one verdict per item and no others:

{"group": "JR", "article_sha256": "<as given>", "justify_sha256": "<as given>", "judged_at": "<ISO-8601 UTC>",
 "verdicts": [{"rule": "<id>", "verdict": "accept|reject", "reason": "<one sentence>"}]}
