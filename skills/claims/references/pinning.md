# Pinning a passage

A pin ties a claim to the words a source actually contains. The engine finds the passage by plain string search in
the text you saved; no model writes or extracts it. If the passage isn't there, the pin is refused. That refusal is
the point: it catches a paraphrase passed off as a quote.

## The loop: save, pin, paste, recheck

1. **Save.** Fetch the page with whatever fetch the host has (a browser, a fetch tool, a download), then save its
   text under the `sources_dir` (default `.plainspoken/sources/`; `RUN paths ARTICLE` prints it as `sources`), one
   file per page, with a name you'll recognise (`example-energy-survey-2025.txt`). Only a file there can be a
   source, and the article can never be its own source: pinning a sentence of the article to the article proves
   nothing. The check is about where the file is, not where its text came from: a copy of the article saved under
   the `sources_dir` would pass it, so the checker and the owner are the backstop there. Save what the fetch
   returned; don't tidy, trim or reword it. Put the page's address in the claim's `source.url`. A page you couldn't
   fetch or save supports nothing this session. A brief from the chat is saved the same way, word for word, and its
   claims carry `source.kind = "brief"` with no `url` (evidence-rules.md).
2. **Pin.** Copy the passage that supports the claim out of the saved file, then run
   `RUN claims pin --source .plainspoken/sources/<file> --passage '<the passage>' --article ARTICLE`. It refuses a
   source outside the `sources_dir` (a link out of it included) or one that is the article. It prints a TOML fragment:
   `passage`, `passage_sha256`, `source_text_sha256`, `retrieved_at` and `source_snapshot`. Keep the passage in
   single quotes: inside double quotes the shell expands `$1,000` to `,000` and the pin is refused. An apostrophe
   inside the passage is written `'\''` (`--passage 'the owner'\''s figure'`). Pass
   `--retrieved-at <ISO 8601>` when the page was fetched earlier than now.
3. **Paste.** Put the fragment under the claim as its `[claims.binding]` table (in a JSON ledger, the same keys in
   `binding`). Then add the five judgements the fragment's comment names, each after reading the passage against the
   claim as the article words it. Never edit the pasted passage or its hashes.
4. **Recheck.** `RUN claims recheck <ledger>` re-reads every saved source, offline, and reports each pinned passage:

   | Result | Means | Do |
   |---|---|---|
   | `ok` | Found, and the hashes match. | Nothing. |
   | `passage_missing` | The saved source no longer holds the passage. | Re-cut from the current text, or re-verify. |
   | `passage_hash_mismatch` | The passage or its hash was edited by hand. | Pin it again. |
   | `source_changed` | The source changed since the pin; the passage is still there. | Re-read around it first. |
   | `snapshot_missing` | The saved file is gone or unreadable. | Save the source again and re-pin. |
   | `snapshot_outside_sources` | The snapshot isn't read: see below. | Save it under `sources_dir`, re-pin. |
   | `unchecked` | No saved source to check against. | Save one and pin from it. |

   `snapshot_outside_sources` means the `source_snapshot` isn't under the `sources_dir` (or links out of it), or is
   the article itself. `source_changed` means re-read the context around the passage before keeping the claim.

## The 80-word cut

A passage is the smallest span that carries the claim, about 75 words at most. The engine refuses anything over
80 words ("passage too long"). Cut to the sentence or two that holds the number, the period, the place and the
population. When those sit in different parts of the page, pin the main passage first and the rest as additional
passages (below), rather than one long span.

## When a pin is refused

"passage not locatable in source text" means the words you gave aren't in the saved file. Typographic quotes,
whitespace and line breaks are already evened out, so the difference is in the words, their case or their markup
(a pin keeps case and markdown link syntax, so copy the passage as the saved file has it). Either:

- re-cut the passage verbatim from the saved file (copy it again; don't retype it); or
- change the claim's status: the source doesn't say what you thought, so the claim is softened, cut or left
  `blocking`.

Never paraphrase a passage, never stitch two spans together with an ellipsis, and never hand-write a hash.

## Additional passages

A compound claim may need more than one span: the figure in one paragraph, the survey's period or sample in
another. Pin the main passage as above, then each further span with `--additional`:

`RUN claims pin --source .plainspoken/sources/<file> --passage '<span>' --additional --locator 'Method'`

It prints an `[[claims.binding.additional_passages]]` item to paste after the binding's fields. When the span is on a
different page, save that page too and add `--source-url https://…` (the article's citation stays `source.url`).
Recheck reads additional passages against the main binding's saved source (so the `sources_dir` rule applies to them
through it), and one from another page shows as `unchecked`.

## Options in short

- `--source`: the saved file, under the `sources_dir` (required).
- `--passage`: the span, copied from that file (required).
- `--article`: the article the claim is in; a `--source` or `--snapshot-path` that is this file is refused.
- `--retrieved-at`: when the page was fetched (default: now).
- `--snapshot-path`: the project-relative path to record as `source_snapshot`, also under the `sources_dir`, when
  the saved file is named another way (default: `--source`'s project-relative path). The file must already be there
  and hold the same text as `--source`, or pin refuses: recheck reads it.
- `--additional`, `--source-url`, `--locator`: for additional passages only.
