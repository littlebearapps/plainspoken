# Regulated claims: an extension point

Some claims carry rules that depend on where you publish and what you sell: health claims, financial product claims,
claims about children, environmental claims and others. Which classes apply, and how serious each one is, is the
publisher's call and their adviser's. The plugin ships no matrix, gives no legal advice, and files no regulated-claims
findings until you give it a matrix.

## Adding your matrix

Write a markdown or TOML file that lists your classes, then name it in `.plainspoken/config.toml`:

```toml
[claims]
regulated_matrix = "docs/regulated-claims.md"
```

The path is relative to the project root. `RUN claims checker-input ARTICLE` passes it to the `claims-checker` as
`regulated_matrix`; with no matrix set, the checker gets `none` and doesn't invent one.

For each class, give the checker what it needs to apply it:

- a short name (it becomes the finding's class, and a claim's `regulated_class`);
- what puts a claim in the class, with an example or two;
- the severity: `blocking` or `warning`;
- what the fix looks like, in softening terms (attribute, qualify, cut, or hold for the owner's sign-off).

Two rules the matrix should state once, near the top, so the checker applies them the same way every run:

- **A reportage rule.** Attributed reporting of what a regulator or a source said ("the regulator's guidance says
  clinics must…") isn't itself a regulated claim; the claim is the article's own promise to the reader. Say whether
  your classes cover reportage, and how an attributed line has to read to count as reportage.
- **A sign-off rule.** Say which classes a person may sign off (a `human_signoff` on the claim, bound to its exact
  wording) and who that person is, and which classes can't be signed off and must be cut or reworded.

An invented example, for a made-up clinic:

```markdown
## outcome_promise (blocking)
A claim that a treatment will produce a result for the reader ("you'll be pain-free in a week").
Fix: describe what the treatment involves, or cut. Hold for the owner's sign-off.
```

## In the ledger

Tag a claim with `regulated_class = "<name>"` when it falls in a class. The skill's report lists every tagged claim
under "Needs the owner": deciding whether it can publish is theirs, not the skill's.
