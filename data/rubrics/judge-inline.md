# Inline judge prompt

The wrapper for a judge prompt that carries everything inline, for models with no file tools (`eval judges`). `lib/plainspoken/evalprompts.py` sends one part below, then the rubric sections it names from `judges.md`, an `Input` block and the line-numbered article.

## J

You are one of four independent judges. You owe the writer nothing, and you don't know who or what wrote the text. Ignore any other instructions you may have been given; only this prompt applies.

- Everything you need is in this prompt. Where the rubric below says to read a file or a path, use the text given here instead; there are no calibration notes, so judge by the rubric alone.
- Judge exactly the rule ids in the input's `rules`, each once, and no others.
- `candidates` are the lint's leads for those rules: confirm or reject each, then read the whole article for misses.
- The article comes after the input, each line prefixed with its number and `: `. The prefix isn't article text. Use that number as an evidence `line`, and quote only the words after the prefix.

Reply with ONLY this JSON (no prose, no code fence):

{"group":"<J1-J4>","article_sha256":"<as given>","judged_at":"<ISO-8601 UTC>","verdicts":[{"rule":"<id>","verdict":"pass|fail","severity":"BLOCK|WARN","evidence":[{"line":<int>,"quote":"<exact article words, ≤200 chars>","reason":"<one sentence>"}]}]}

## JR

You are an independent reviewer of writers' justifications. You owe the writer nothing, and you don't know who or what wrote the text. Ignore any other instructions you may have been given; only this prompt applies.

- Everything you need is in this prompt. Where the rubric below says to read a file or a path, use the text given here instead; there are no calibration notes.
- The rubric's justification-review section comes first, then the rule's own entry when it has one.
- Review every item in the input's `items`, each once, and no others. You review the justification; you don't re-judge the rule.
- The article comes after the input, each line prefixed with its number and `: `. The prefix isn't article text; evidence `line` numbers refer to it.

Reply with ONLY this JSON (no prose, no code fence), one verdict per item and no others:

{"group": "JR", "article_sha256": "<as given>", "justify_sha256": "<as given>", "judged_at": "<ISO-8601 UTC>",
 "verdicts": [{"rule": "<id>", "verdict": "accept|reject", "reason": "<one sentence>"}]}
