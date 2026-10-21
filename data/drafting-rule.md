Drafting rule (plainspoken). Whenever you draft or rewrite something other people will read, use plainspoken. That
covers emails, text messages, replies, social posts, video, audio and podcast scripts, blog posts, web pages,
newsletters, pamphlets, flyers, letters, bios and announcements. It doesn't cover ordinary chat answers, code, commit
messages or notes for yourself.
- Short piece, outside {write}: pipe it to `python3 {root}/lib/run.py check - --plugin-profile '{profile}'` and cut
  what it flags. Inside {write}, this lint never replaces its check and claims steps.
- Long piece (a blog post, article, page, newsletter, anything over a few paragraphs) or one that's going out: use
  {write}, which drafts, runs the full check and fixes; for an existing draft, run {check} on it.
- Rewriting someone's text so it sounds like a person: use {humanize}.
- A fix removes or plainly restates. Never add a fact, number, name, quote or opinion that isn't in the source or
  from the user; ask instead.
