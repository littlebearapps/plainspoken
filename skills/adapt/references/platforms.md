# Platform notes for adapt

Each section gives the format, a length budget, how links and tags work, and what that platform's readers expect.
Only the `Limit` figures come from the source under `Checked`: they're the platforms' own figures on the date shown,
not rules this plugin sets. The format, hook, link, hashtag and "Readers expect" notes are this plugin's general
guidance, not the platforms' own figures or rules. Platforms count differently (Bluesky counts graphemes, and
platforms treat links in their own ways), so every budget below keeps a margin under the limit. `length` counts
characters as a reader sees them: a flag, an accented letter or an emoji family is one. Re-check a figure before
relying on it: platforms change them.

## LinkedIn

- Format: a plain-text post, short paragraphs, a blank line between them. Light formatting only. One idea.
- Limit: LinkedIn's help page gives 3,000 characters for a post. Budget: 1,300 characters or fewer for most posts.
- Hook: the opening lines are what shows before the feed cuts the post off, so the point goes first. Don't open on a
  greeting or on the article's title.
- Links: one link, near the end. A post that is only a link and a headline gives the reader no reason to click.
- Hashtags: two or three at most, at the end, and only if they are words a reader would search.
- Readers expect: a worked observation or a decision with a reason, written by a person, in the first person.
- Checked: 2026-10-12, https://www.linkedin.com/help/linkedin/answer/a528176

## Bluesky

- Format: one short plain-text post. Several posts in a thread only when each stands on its own.
- Limit: 300 graphemes per post, set in the app.bsky.feed.post record definition. Budget: 240 or fewer, which leaves
  room for a link and a tag.
- Links: keep the link's length inside the budget, because a long address eats it. Put it last.
- Hashtags: one or two, or none.
- Readers expect: a plain, direct line with a point of view. No headline-and-link announcements.
- Checked: 2026-10-12, https://raw.githubusercontent.com/bluesky-social/atproto/main/lexicons/app/bsky/feed/post.json

## Mastodon

- Format: one short plain-text post. Use a content warning for a long or heavy post if the community expects one.
- Limit: 500 characters by default, per Mastodon's documentation; an individual server can set a different limit.
  Budget: 400 or fewer. If the user says their server sets a different limit, ask for it and budget under that.
- Links: keep the link's length inside the budget and put it last.
- Hashtags: a few, at the end, with each word capitalised (CamelCase) so screen readers can read them.
- Readers expect: craft and detail over promotion. A post that sounds like an advert is ignored.
- Checked: 2026-10-12, https://docs.joinmastodon.org/user/posting/

## Reddit

- Format: a title and a body (markdown is available in the body), written for one named community and its rules.
- Limit: unconfirmed. No official Reddit help page confirming a title or body limit was found. Budget: a title of 100
  characters or fewer and a body of 2,000 characters or fewer.
- Links: a link in the body only when the community allows it, and after the point has been made.
- Hashtags: none. Communities use flair instead.
- Readers expect: someone taking part, not announcing. Say what you did, what happened and what you'd do differently.
  Ask the user which community, and check its rules before drafting.
- Checked: unconfirmed

## Newsletter

- Format: a subject line, an opening that works as a preview, short sections and one link or action at the end.
- Limit: unconfirmed. Limits depend on the sending tool, and none was named. Budget: 400 to 700 words, with the
  subject at 60 characters or fewer.
- Links: one main link. Describe where it goes in words, not "click here".
- Hashtags: none.
- Readers expect: something they'd miss if it didn't come, written to one person, with the main point inside the first
  few lines.
- Checked: unconfirmed
