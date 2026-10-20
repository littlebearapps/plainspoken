# Third-party notices

plainspoken incorporates the components below. Each keeps its own licence.

| Component | Source | Licence | Used in |
|---|---|---|---|
| humanizer (pattern catalogue) | https://github.com/blader/humanizer | MIT | skills/humanize |

Wikipedia "Signs of AI writing" (https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)
is CC BY-SA 4.0. plainspoken paraphrases the page and cites it. One overlap comes from the vendored humanizer
catalogue (`skills/humanize/references/patterns.md`, kept verbatim from upstream): 11 of its short "before" examples,
machine-generated sentences shown as the thing to fix, also appear on that Wikipedia page, where they're quoted as
examples of AI output. Nothing else in plainspoken copies the page's wording.

## skills/humanize

skills/humanize is adapted from blader/humanizer v3.1.0 (tag commit `225a6f39ac85f76ee48dbad772ea4abe4ed6c9d8`).
The pattern catalogue is verbatim; the preamble is plainspoken's, and two sentences and one clause are deleted (see docs/provenance.md).
Upstream licence, in full:

```text
MIT License

Copyright (c) 2025 Siqi Chen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
