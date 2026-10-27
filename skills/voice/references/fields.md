# Voice profile fields

Every key in `templates/voice-profile.toml`, what it does, an invented example and who reads it. "The checker" is
the lint and judges. "The voice check" is `/plainspoken:voice check`. "Drafting" covers `write`, `adapt` and
`/plainspoken:voice apply`. `/plainspoken:voice build` writes the file; after that, skills read it only through the
CLI (`profile --voice`, `anchors`, `register-checklist`), never by opening the TOML. A key that `profile --voice`
doesn't print reaches no drafting skill.

## Profile and checker settings

- `[profile]` `name`, `locale`, `flags`: the profile's name, its spelling conventions and any extra switches
  (`narrative` relaxes the sentence-rhythm rules). Example: `name = "my-voice"`. Who reads it: the checker
  (register-check's checklist also names the locale).
- `[thresholds]`: numeric limits that replace the ruleset's defaults, by rule name. Example: a higher em-dash cap for
  a writer who uses them. Who reads it: the checker.
- `[lexicon]` `extra_bans`: words or names you never want in print. Example: `["Acme"]`, a former employer's name.
  Who reads it: the checker.
- `[document]`: how a file is read (visible frontmatter keys, the FAQ key, headings that hold lists, headings that
  may carry long sentences). Who reads it: the checker.
- `[rules]` `disabled`: rule ids switched off for this profile. Who reads it: the checker.
- `[judges]` `calibration_notes`: a notes file next to the profile that the judges read. Who reads it: the checker.

## Identity and voice

- `pronoun`: `I`, `we` or `either`. Example: `I`. Who reads it: drafting, the voice check and register-check.
- `writer`: one line on who is speaking. Example: "A volunteer who runs the garden newsletter." Who reads it:
  drafting and the voice check.
- `principles`: things the author does, each pointing at a sample. Example: "Names the plant, the bed and the
  date." Who reads it: drafting and the voice check.
- `opinion_pattern`: how the author states a view. Example: "View first, then the reason, then what might change
  it." Who reads it: drafting and the voice check.
- `humour`, `emoji_max`, `exclamation_max`: how much of each the author uses. Example: `"dry, sparing"`, `0`, `1`.
  Who reads it: drafting and the voice check.
- `tone`: a table of 0 to 1 scales (`formal_casual`, `serious_funny` and so on). Example: `formal_casual = 0.7`.
  Who reads it: drafting and the voice check.
- `tone_notes`: one line per scale with the sample that shows it. `profile --voice` prints each note beside its scale.
  Who reads it: drafting and the voice check.

## Rhythm

- `sentence_mean`, `sentence_sd`, `burstiness`, `long_share`, `short_share`: measured from the samples by
  `voice-stats`. Example: `sentence_mean = 14.2`. Who reads it: drafting and the voice check, as a guide. The checker
  ignores these.
- `notes` (under `[rhythm]`): the pattern in words. Example: "Short answers, then one long walk-through." Who reads
  it: drafting and the voice check.

## Reader

- `persona`: who reads this writing, in a line. Describe what the reader hasn't been exposed to, never their age or
  ability. Example: "a neighbour who gardens on weekends". Who reads it: drafting, `plain-language`, the voice
  check and register-check (its checklist names the reader).
- `comprehension_floor`: the school year a reader needs to follow the text, 1 to 12. Example: `7`. Who reads it:
  drafting, `plain-language` and the voice check.
- `glossary`: a file next to the profile with plain-word swaps. `profile --voice` prints its full path. Who reads
  it: `plain-language`.
- `knows`: what the reader already knows. Example: `["seasons", "watering"]`. Who reads it: nothing yet. The schema
  accepts it, but `profile --voice` doesn't print it in v0.2.

## Writing types

- `blends`: `answer-first` or `narrative`, per kind of writing (article, page, email, social). Who reads it: drafting.
  The four slots are fixed, so map each kind of writing onto one: `email` for emails, texts and direct messages,
  `social` for posts, `page` for web and landing pages, `article` for blog posts, reports, proposals, guides and
  newsletters (`guides/voice-profiles.md`).
- `formatting`: one line of layout rules per kind of writing. Example: "Plain text. One ask." Who reads it: drafting,
  for the one kind it's drafting (`profile --voice --type <kind>`). Start the line by naming what the slot covers
  ("Emails, texts and DMs. …"). A rule for every kind belongs in `principles` instead.
- `topics` (under `[avoid]`): subjects to stay off. Who reads it: drafting and the voice check.
- `moves` (under `[avoid]`): things the author never does. Example: "Opens with a dictionary definition." Who reads
  it: the voice check. `profile --voice` prints them for every skill, but drafting is told not to steer by them.
- `starters`, `fillers`, `closers` (under `[lexicon]`): habits seen at least twice in the samples. Who reads it:
  drafting and the voice check.

## Registers and anchors

- `registers`: `[[registers]]` entries (`name`, `pronoun`, `formality`, `notes`) for a way of writing in one setting.
  Example: an `email` register, casual-professional. Who reads it: register-check, through
  `register-checklist --register <name>` (its `pronoun` and `formality`). The plain `profile` summary lists the
  names. `profile --voice` doesn't print registers, so drafting doesn't see them, and nothing reads `notes` in v0.2.
- `anchors`: `[[anchors]]` entries, passages in the author's own voice. Each has an `id`, `tags` (section types), a
  `source`, and either `text` or `path` with `lines`. A `path` must sit inside the project. Who reads it: drafting
  and the voice check.
