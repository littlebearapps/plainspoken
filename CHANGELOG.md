# Changelog

Every plainspoken release, newest first. Before 1.0, versions follow semantic versioning with a minor release for
new features and a patch release for fixes. release-please writes each entry from the commit messages; the plain
"In short" lines were added by hand, and so were the corrections where a commit only referred to an issue
but the entry said it closed it.

## [0.12.0](https://github.com/littlebearapps/plainspoken/compare/v0.11.0...v0.12.0) (2026-10-30)

In short: the publish gate, write guard and kaizen nudge now run in Codex and Hermes Agent, `doctor` checks an
install, optional checks read the writing in tool calls and chat replies, and the judges wait for a read lint and a
current claims status. Write reports copy their figures from the engine and are sent back when they ask the owner about
lines the engine doesn't list. [#75](https://github.com/littlebearapps/plainspoken/issues/75) and
[#162](https://github.com/littlebearapps/plainspoken/issues/162) stay open: their fixes shipped, but round 8 showed
they don't fully hold yet.


### Features

* **adapt:** intake forms offer the common situations in the reader's words, plus a "not sure where to start" option ([38bbd18](https://github.com/littlebearapps/plainspoken/commit/38bbd18acd7560c4532ac1cb97563ab452b43e36))
* **ci:** lint verdict diff on a public corpus, base against head ([fe6f66d](https://github.com/littlebearapps/plainspoken/commit/fe6f66de517744be8b6e9129b4e9b7e039e81e3e)), closes [#100](https://github.com/littlebearapps/plainspoken/issues/100)
* **codex:** publish gate, write guard and kaizen nudge hooks ([5d83728](https://github.com/littlebearapps/plainspoken/commit/5d8372892171bae962c1b3a69bdba62ca40688eb)), closes [#88](https://github.com/littlebearapps/plainspoken/issues/88)
* **copy-audit:** a decision page runs in the order of the reader's questions, with the action once they can decide, and a site keeps one name per thing ([4a715c2](https://github.com/littlebearapps/plainspoken/commit/4a715c2f87ebaf02faf7f342a24605dc64be65e7))
* **eval:** drift check for judge runs and trigger evals ([fbadefd](https://github.com/littlebearapps/plainspoken/commit/fbadefd57f81796ef136d8b3fb7c879f3b64d652)), closes [#102](https://github.com/littlebearapps/plainspoken/issues/102)
* **hermes:** publish gate, write guard and kaizen nudge hooks ([6ae264b](https://github.com/littlebearapps/plainspoken/commit/6ae264b10c1c9bf7cc5c3b7e319c0216a1ce2ebd)), closes [#90](https://github.com/littlebearapps/plainspoken/issues/90)
* **hooks:** check the writing in a tool call (an email, a post, a message) before it goes out ([ba3eeb5](https://github.com/littlebearapps/plainspoken/commit/ba3eeb589e0b2b80c5cac49c32ccef514848a960)), closes [#124](https://github.com/littlebearapps/plainspoken/issues/124)
* **hooks:** tell you what the lint found in a draft written into the chat reply, never the model ([e2b240b](https://github.com/littlebearapps/plainspoken/commit/e2b240b23e1efa967c1e33e80b32dca5673ce1aa)), closes [#125](https://github.com/littlebearapps/plainspoken/issues/125)
* **kaizen:** add a neutral mining-drafter agent for kaizen mine ([b2b3002](https://github.com/littlebearapps/plainspoken/commit/b2b30020daf01257ac1cd5cf7c779f66393ecb0b))
* **kaizen:** apply every approved proposal with `kaizen apply --all-approved` ([817573c](https://github.com/littlebearapps/plainspoken/commit/817573cce01737c32cb73eabe5e4563ca5b63aa5))
* **kaizen:** share one monthly proposal cap between calibrate and mine ([c4fceeb](https://github.com/littlebearapps/plainspoken/commit/c4fceebb83948ff017231c1e1ba62ff929d15833))
* **kaizen:** show an apply to a checkout as awaiting release until it ships ([8a45ba8](https://github.com/littlebearapps/plainspoken/commit/8a45ba8d22df5a627855254d0a1147bdedfd8a24))
* **locale:** the locale option now sets which English the skills write in, overridable by [locale] variant ([122df3c](https://github.com/littlebearapps/plainspoken/commit/122df3c4f2fddc4396639c37e065426eb3217d86)), closes [#121](https://github.com/littlebearapps/plainspoken/issues/121)
* **plain-language:** a reader who uses a term may not know it; the persona describes exposure, not ability ([f0870a7](https://github.com/littlebearapps/plainspoken/commit/f0870a7b4c99a1cd7b0002254de35b1ce939271e))
* **plain-language:** flag words that hide scope, goals the source never gave, and parts named before their job ([904e304](https://github.com/littlebearapps/plainspoken/commit/904e304ebdf9e6c11fd28735bf4e76cb84be848c))
* **register-check:** first contact judges the easy no by the message's shape and flags sales scaffolding ([8c43b14](https://github.com/littlebearapps/plainspoken/commit/8c43b1426710fa8564c1f3406c992135740bea5c))
* **register-check:** flag a limit worded as if more evidence would make the outcome promisable ([ba548e7](https://github.com/littlebearapps/plainspoken/commit/ba548e71fed7cb9d762cecc646fcf8485075606e))
* **setup:** warn-only host checks in setup, and a doctor command ([#119](https://github.com/littlebearapps/plainspoken/issues/119)) ([86b262b](https://github.com/littlebearapps/plainspoken/commit/86b262b44ef8e2e9aa6252b9bc61cc8c104a3f2b))
* **write:** a multi-section page reads section design before its headings are written ([bd8db11](https://github.com/littlebearapps/plainspoken/commit/bd8db11a9d16a639b59ec133ac0a4b9b23bc3fbe))
* **write:** a recommendation someone else carries out names the item, the change, the role and the confirmation ([556e05f](https://github.com/littlebearapps/plainspoken/commit/556e05f5fe884b583b489a9312e40204cf424b87))
* **write:** check the premise of a message about the reader's own material before drafting it ([8344f07](https://github.com/littlebearapps/plainspoken/commit/8344f07daf0b9978e4b4b7e529f9084390db634b))
* **write:** replies answer each question asked, acknowledge a raised worry first, and ask what settles a missing fact ([270491c](https://github.com/littlebearapps/plainspoken/commit/270491c4d9ccf591fe0bd803bfd5181d0a764e67))


### Bug Fixes

* **check:** a 7d fix joins neighbours in their own words or keeps the WARN, never pads ([#165](https://github.com/littlebearapps/plainspoken/issues/165)) ([6042ad3](https://github.com/littlebearapps/plainspoken/commit/6042ad32da431d294d600c98230ded0dfd029493))
* **check:** a profile's stricter dash cap now holds in social posts, and en dashes can be capped ([a23a907](https://github.com/littlebearapps/plainspoken/commit/a23a9072043230f78e0a96028b1938ac04b59d47)), closes [#104](https://github.com/littlebearapps/plainspoken/issues/104)
* **claims:** a brief's call to action is a source, and a pinned claim is judged on its passage ([#167](https://github.com/littlebearapps/plainspoken/issues/167)) ([095ed4e](https://github.com/littlebearapps/plainspoken/commit/095ed4ebf61f04e9f5e8a4ba8385d9978845e138))
* **claims:** any result for a client is sensitive, named or not ([c080629](https://github.com/littlebearapps/plainspoken/commit/c080629c180dd79d5faef2ad2cc6e48d77289909)), closes [#76](https://github.com/littlebearapps/plainspoken/issues/76)
* **claims:** chain one step's CLI calls with && instead of one Bash call each ([e17bd14](https://github.com/littlebearapps/plainspoken/commit/e17bd1448991febbd22b1179f62fab3df16a543b)), closes [#78](https://github.com/littlebearapps/plainspoken/issues/78)
* **copy-audit:** a review the reader asked for states the problem plainly ([6c293a6](https://github.com/littlebearapps/plainspoken/commit/6c293a6160ae4e9d89b6fb73aa4ea9181b7bc839))
* **copy-audit:** call a pattern seen once a single example, as the evidence guide does ([37007dc](https://github.com/littlebearapps/plainspoken/commit/37007dc1fa61c30c992e49649f1f25addbd4a780))
* **evals:** a spelled count of names the source lists is derived, not new ([#169](https://github.com/littlebearapps/plainspoken/issues/169)) ([7581f00](https://github.com/littlebearapps/plainspoken/commit/7581f000452fb93ac99f2440e8fadb92403468ff)), closes [#158](https://github.com/littlebearapps/plainspoken/issues/158)
* **gate:** say nothing is gated when warn or block has no [gate] paths ([db79fe3](https://github.com/littlebearapps/plainspoken/commit/db79fe30f72f16eebd2912bc7609088f05af23a3)), closes [#94](https://github.com/littlebearapps/plainspoken/issues/94)
* **hermes:** pass block-mode integrity findings through and say when a hook couldn't run ([#112](https://github.com/littlebearapps/plainspoken/issues/112)) ([2ffd00a](https://github.com/littlebearapps/plainspoken/commit/2ffd00a26241c2a483b589a10b4e7f42d2d3703a))
* **hooks:** catch owner decisions and asks beside listed claims in the report guard ([#170](https://github.com/littlebearapps/plainspoken/issues/170)) ([a649081](https://github.com/littlebearapps/plainspoken/commit/a6490811785fb6b78b7ae5b1f0e79d65b7e78255)), refs [#75](https://github.com/littlebearapps/plainspoken/issues/75)
* **hooks:** expand literal assignments made earlier in the command in the write guard ([#164](https://github.com/littlebearapps/plainspoken/issues/164)) ([b638992](https://github.com/littlebearapps/plainspoken/commit/b6389924ca9053437b73c8a694b38351fd273bfe)), closes [#161](https://github.com/littlebearapps/plainspoken/issues/161)
* **hooks:** send back a write report that leaves out the status block ([#172](https://github.com/littlebearapps/plainspoken/issues/172)) ([885cf91](https://github.com/littlebearapps/plainspoken/commit/885cf91600304cc704c11af4360bda7080fd28af)), closes [#171](https://github.com/littlebearapps/plainspoken/issues/171)
* **hooks:** show the flagged lines in the tool-call check's ask prompt ([#153](https://github.com/littlebearapps/plainspoken/issues/153)) ([2552c1f](https://github.com/littlebearapps/plainspoken/commit/2552c1f589f51a325932c6f302e174fac5df88df)), closes [#152](https://github.com/littlebearapps/plainspoken/issues/152)
* **hooks:** the writing nudge no longer fires on questions about hooks or on tech tasks that mention emails ([f03492e](https://github.com/littlebearapps/plainspoken/commit/f03492ef0c2349d524e006aa654edda7e2a9f29e)), refs [#125](https://github.com/littlebearapps/plainspoken/issues/125)
* **humanize:** a request for the text only gets the text only ([#159](https://github.com/littlebearapps/plainspoken/issues/159)) ([faaa186](https://github.com/littlebearapps/plainspoken/commit/faaa186348326efcc1821da1a198006b0d7071b5)), closes [#157](https://github.com/littlebearapps/plainspoken/issues/157)
* **humanize:** read the voice profile when used on its own ([a6ec638](https://github.com/littlebearapps/plainspoken/commit/a6ec6385e7cbe3c26b5e29b6a4daf2fe3ce3b592)), closes [#98](https://github.com/littlebearapps/plainspoken/issues/98)
* **lint:** report which fields were read, and document checking a post's other fields ([#115](https://github.com/littlebearapps/plainspoken/issues/115)) ([0940cee](https://github.com/littlebearapps/plainspoken/commit/0940cee6baa93ae151491435c25ac443e613159a))
* **lint:** say lint only and give BLOCK/WARN counts in the heading, never CLEAN above WARNs ([#114](https://github.com/littlebearapps/plainspoken/issues/114)) ([3b3a842](https://github.com/littlebearapps/plainspoken/commit/3b3a8428aedd5f2c7acdfe59fdc19de41b7e0d33))
* **plain-language:** a rewrite changes only the lines it flagged ([32507d6](https://github.com/littlebearapps/plainspoken/commit/32507d6dfe764e8fbc6a0356364263953e73f58b))
* **profile:** the default profile no longer sets a locale, so default-profile reports need one re-check ([791e0bc](https://github.com/littlebearapps/plainspoken/commit/791e0bc2728292bad2926c964f953d019e48b684)), closes [#121](https://github.com/littlebearapps/plainspoken/issues/121)
* **reader-value:** chain one step's CLI calls with && instead of one Bash call each ([cfc1725](https://github.com/littlebearapps/plainspoken/commit/cfc172590342dd936bfb5da3c3c5c46889720ab8)), closes [#92](https://github.com/littlebearapps/plainspoken/issues/92)
* **write:** a limit that would change the reader's decision sits beside its claim, not at the close ([641fe6f](https://github.com/littlebearapps/plainspoken/commit/641fe6f38b8f447ae165f3da5a02a195312ddc77))
* **write:** a report that asks the owner to check a line the engine doesn't list is sent back to cut or hold it ([99799b6](https://github.com/littlebearapps/plainspoken/commit/99799b6230183189b09089b52000b20cb5875637)), refs [#75](https://github.com/littlebearapps/plainspoken/issues/75)
* **write:** copy the report's figures and statuses from the engine lines ([#168](https://github.com/littlebearapps/plainspoken/issues/168)) ([1355edb](https://github.com/littlebearapps/plainspoken/commit/1355edbb3a72c3eba313ec47cf4589347ea35c4f)), closes [#163](https://github.com/littlebearapps/plainspoken/issues/163)
* **write:** judges wait for a current claims status and a read lint ([#166](https://github.com/littlebearapps/plainspoken/issues/166)) ([ef53ee4](https://github.com/littlebearapps/plainspoken/commit/ef53ee49ec7907a5ec621eb6d20fe6ac6664f2f1)), closes [#160](https://github.com/littlebearapps/plainspoken/issues/160), refs [#162](https://github.com/littlebearapps/plainspoken/issues/162)
* **write:** label the report's Reader value line as outline-only ([#116](https://github.com/littlebearapps/plainspoken/issues/116)) ([c50208c](https://github.com/littlebearapps/plainspoken/commit/c50208cf653afced3cbd4648252620ab5f1c8c7b))


### Documentation

* a short README hub, with install, configuration, checking, claims, FAQ and troubleshooting guides ([9856d57](https://github.com/littlebearapps/plainspoken/commit/9856d57f39f63b5197a837a5104333798992898d))
* **acceptance:** round 7 (paused) and round 8 results ([#173](https://github.com/littlebearapps/plainspoken/issues/173)) ([c533408](https://github.com/littlebearapps/plainspoken/commit/c5334089019d8e54613a190fc5b3ac4d0d6f1918))
* **changelog:** plain summaries per release, the releases before 0.5.0, and corrected 0.5.0 and 0.6.0 entries ([1ab3ea2](https://github.com/littlebearapps/plainspoken/commit/1ab3ea2c34d45192ffdaf43745c849eaaec0326e))
* **check:** a report-only route that never edits the file ([#117](https://github.com/littlebearapps/plainspoken/issues/117)) ([0f0f29a](https://github.com/littlebearapps/plainspoken/commit/0f0f29a5fb851873f0a75b6c2df69d844af5f0dd))
* contributing, code of conduct, security, support, roadmap, and issue and PR templates ([b3a3cfb](https://github.com/littlebearapps/plainspoken/commit/b3a3cfb4905ec08cb3aa1c48d21a3353dbf15c7b))
* **evidence-method:** studying other organisations' pages starts from one question, tests fit against the profile, and says what was and wasn't taken ([93cdff4](https://github.com/littlebearapps/plainspoken/commit/93cdff43dc0ff148b734c1985ac529d64b301eb1))
* explain the tool-call check, its modes per host and what it can't see ([0ef7af4](https://github.com/littlebearapps/plainspoken/commit/0ef7af4b264855570c5bdd9d5a5a756f97f5626b)), closes [#124](https://github.com/littlebearapps/plainspoken/issues/124)
* **facts:** record the round-8 live probes of the tool-call and chat-reply checks ([#155](https://github.com/littlebearapps/plainspoken/issues/155)) ([c283622](https://github.com/littlebearapps/plainspoken/commit/c283622b248f0d5b9a02a28b30adb91e2261bdd8))
* **facts:** sandbox writes to .plainspoken, and omitClaudeMd on 2.1.308 ([166b14f](https://github.com/littlebearapps/plainspoken/commit/166b14f1c379f01a0974775a8c9450c2688e9ea9))
* Hermes launch flags, README versions, what a judge record proves, what stays on disk ([#118](https://github.com/littlebearapps/plainspoken/issues/118)) ([ccdbed6](https://github.com/littlebearapps/plainspoken/commit/ccdbed62a570a170f25949cde33cbb32218cb604))
* **kaizen:** K1–K6 evidence as of 2026-10-23 ([45e9f64](https://github.com/littlebearapps/plainspoken/commit/45e9f64c5d9e7b0ace2eb5cd51124d30e2686fd0))
* **locale:** say what the locale setting does, who wins, and how to set it on each host ([1b888c2](https://github.com/littlebearapps/plainspoken/commit/1b888c23c9f5d1cf1267797b97856ba336e66ec3)), closes [#121](https://github.com/littlebearapps/plainspoken/issues/121)
* point questions and ideas to GitHub Discussions ([befba93](https://github.com/littlebearapps/plainspoken/commit/befba93d6feeec77b8ab0d22092fb72abe37dc8d)), closes [#122](https://github.com/littlebearapps/plainspoken/issues/122)
* say Codex asks you to trust plainspoken's hooks again after every update ([19c1353](https://github.com/littlebearapps/plainspoken/commit/19c13533d812ce472747b7ef029e7d8352767c09))
* **voice:** one profile for every kind of writing ([#105](https://github.com/littlebearapps/plainspoken/issues/105)) ([9ed4c67](https://github.com/littlebearapps/plainspoken/commit/9ed4c67c35aca239550f3d9b2d4855361f580877))

## [0.11.0](https://github.com/littlebearapps/plainspoken/compare/v0.10.1...v0.11.0) (2026-10-22)

In short: the claims checker gets its own golden set to be measured against, the judges wait until open lint findings
are dealt with, and the writing nudge and write guard misfire less.


### Features

* **evals:** claims-checker golden set and an eval claims runner ([8d4c484](https://github.com/littlebearapps/plainspoken/commit/8d4c484434efc028223b3ebf78947d2a65bcb73c)), closes [#59](https://github.com/littlebearapps/plainspoken/issues/59)


### Bug Fixes

* **check:** a 7d join links with "and" or "but" and adds nothing ([9f0f875](https://github.com/littlebearapps/plainspoken/commit/9f0f8750f4b280aaa9ca8d0a85b8a35fb9bdb138)), closes [#73](https://github.com/littlebearapps/plainspoken/issues/73)
* **check:** judge-input holds back an open lint BLOCK or WARN ([d7cac24](https://github.com/littlebearapps/plainspoken/commit/d7cac24818579c9a51233102ab739567eb6e8bbb)), closes [#74](https://github.com/littlebearapps/plainspoken/issues/74)
* **hooks:** write guard lets reads through and reads a script run by name ([52195c6](https://github.com/littlebearapps/plainspoken/commit/52195c6a499a61a94bf486dd2898a589f1d96b7a)), closes [#57](https://github.com/littlebearapps/plainspoken/issues/57)
* **judges:** input_digest hashes the whole judge-input line ([e8d1463](https://github.com/littlebearapps/plainspoken/commit/e8d1463333859fbec6a71089b11c5eec0bd397ab)), closes [#61](https://github.com/littlebearapps/plainspoken/issues/61)
* **nudge:** ignore host wrapper blocks before reading the ask ([36bc1d5](https://github.com/littlebearapps/plainspoken/commit/36bc1d532651ae33a0a9b1b15dfab14c3e122a1e)), closes [#55](https://github.com/littlebearapps/plainspoken/issues/55)
* **status:** the words line says what it counts ([281e2bc](https://github.com/littlebearapps/plainspoken/commit/281e2bc4e90ff6056c1c85dea3bdce37a4223532)), closes [#63](https://github.com/littlebearapps/plainspoken/issues/63)

## [0.10.1](https://github.com/littlebearapps/plainspoken/compare/v0.10.0...v0.10.1) (2026-10-22)

In short: drafting is routed by the size of the piece, not its name, lint findings are fixed before the judges run,
and judge-record and claims refuse replies built by hand or written by a shell command.


### Bug Fixes

* **check:** fix lint findings before the judges; write does it before claims ([eeed1b7](https://github.com/littlebearapps/plainspoken/commit/eeed1b7b8d977e8522b07ca7cde483968c514083)), closes [#42](https://github.com/littlebearapps/plainspoken/issues/42)
* **claims:** refuse shell writes to reply files and the ledger; judge each claim's binding ([d835da7](https://github.com/littlebearapps/plainspoken/commit/d835da790074a952e77063fade80609ad8a8b033)), closes [#44](https://github.com/littlebearapps/plainspoken/issues/44)
* **evals:** fact graders take numbers in words, and the bin thread needn't name its own council ([c9862de](https://github.com/littlebearapps/plainspoken/commit/c9862deb92ba71d0d5c9e02a2e4699452a56248c)), closes [#47](https://github.com/littlebearapps/plainspoken/issues/47)
* judge-record refuses a reply to a hand-built judge input ([5670d36](https://github.com/littlebearapps/plainspoken/commit/5670d36f07b502ccac619e0e60cab5fa978dd53b)), closes [#43](https://github.com/littlebearapps/plainspoken/issues/43)
* route drafting by the piece's size, not its type name ([48c9580](https://github.com/littlebearapps/plainspoken/commit/48c95808ce9d86cab48f2310f779768e874339de)), closes [#37](https://github.com/littlebearapps/plainspoken/issues/37)
* **write:** needs the owner comes from the ledger; a fact labelled opinion fails claims ([396ed13](https://github.com/littlebearapps/plainspoken/commit/396ed13e9db5ccf09dc86ca0509390e948a5c42e)), closes [#45](https://github.com/littlebearapps/plainspoken/issues/45)
* **write:** start the report with the status block, shortfall after it ([3bb5a30](https://github.com/littlebearapps/plainspoken/commit/3bb5a30cb4c67adf8616b144dd0f4ffd5a55f07f)), closes [#41](https://github.com/littlebearapps/plainspoken/issues/41)

## [0.10.0](https://github.com/littlebearapps/plainspoken/compare/v0.9.0...v0.10.0) (2026-10-22)

In short: `check --no-record` for a look that records nothing, `judge-record --all`, briefs as saved claims sources
with `claims stamp`, many check and write fixes, and Hermes Agent's install scan now rates the plugin safe.


### Features

* **check:** add --no-record, a read-only lint that records no kaizen events ([a64ebc8](https://github.com/littlebearapps/plainspoken/commit/a64ebc8e81fd9e13958391a0dd181c2f7e5c74a9)), closes [#1](https://github.com/littlebearapps/plainspoken/issues/1)
* **check:** record all four judge replies in one call with `judge-record --all` ([d30fb14](https://github.com/littlebearapps/plainspoken/commit/d30fb144a662896f8557c85914868e1e8910f292)), closes [#28](https://github.com/littlebearapps/plainspoken/issues/28)
* **claims:** brief as a saved source, `claims stamp`, and a plain edit/record order ([9c02702](https://github.com/littlebearapps/plainspoken/commit/9c02702efed7a623a44db18f144379eb0146a6e6)), closes [#31](https://github.com/littlebearapps/plainspoken/issues/31)


### Bug Fixes

* **check:** name only the tripped 12f slop metrics, with values and limits ([1ae3365](https://github.com/littlebearapps/plainspoken/commit/1ae3365d844a2b3422291debec5301b6cebde225)), closes [#26](https://github.com/littlebearapps/plainspoken/issues/26)
* **check:** one fix rule (cut, join, split or restate) that the 7d and 12f remedies fit ([36ecffd](https://github.com/littlebearapps/plainspoken/commit/36ecffdaa71fa61d917344024facab04e74eb3cd)), closes [#30](https://github.com/littlebearapps/plainspoken/issues/30)
* **check:** say which edits are fix passes and report from run.py status ([ed25d24](https://github.com/littlebearapps/plainspoken/commit/ed25d2438dafd7193b3b45bc703dbe4f6005b73c)), closes [#29](https://github.com/littlebearapps/plainspoken/issues/29)
* **check:** scale the 12f opening-repetition limit with length ([ba8bcbb](https://github.com/littlebearapps/plainspoken/commit/ba8bcbb7f7acaac8d7f32684a281e121701565f3)), closes [#25](https://github.com/littlebearapps/plainspoken/issues/25)
* **eval:** count numbers in words, and list derived numbers apart from new ones ([14996f1](https://github.com/littlebearapps/plainspoken/commit/14996f13b8f99a43fb1abbb4e3acd0d3aecbe9ae)), closes [#33](https://github.com/littlebearapps/plainspoken/issues/33)
* **evals:** grade only the piece between the markers, and drop the club name from the netball facts ([a003eea](https://github.com/littlebearapps/plainspoken/commit/a003eea9d48b2853f08bcf23ac18e5bbd23c360d)), closes [#34](https://github.com/littlebearapps/plainspoken/issues/34)
* **kaizen:** apply --target profile edits the proposal's own profile ([e99a2a1](https://github.com/littlebearapps/plainspoken/commit/e99a2a1df6ab7cf8c033582b87f00e8f0b882ca2)), closes [#2](https://github.com/littlebearapps/plainspoken/issues/2)
* **skills:** run the profile call as an explicit first step, not a load-time command ([d668820](https://github.com/littlebearapps/plainspoken/commit/d6688202f2acacb696ec5bb089dc8126b0659e5f)), closes [#12](https://github.com/littlebearapps/plainspoken/issues/12)
* **write:** raise a length the sources can't carry before drafting, and report the real word count ([f405242](https://github.com/littlebearapps/plainspoken/commit/f405242070c7a24a11034b4e30c265405f4a02da)), closes [#32](https://github.com/littlebearapps/plainspoken/issues/32)
* **write:** report the check and claims results from the engine, never from memory ([0e08d3f](https://github.com/littlebearapps/plainspoken/commit/0e08d3f7c0d47b40cb386a1eedcfca13525fea16)), closes [#24](https://github.com/littlebearapps/plainspoken/issues/24)
* **write:** run claims before the check, so claims edits don't force a second round of judges ([36c9e4a](https://github.com/littlebearapps/plainspoken/commit/36c9e4a4258d7f1ce28eab88e26653ccb32821f8)), closes [#27](https://github.com/littlebearapps/plainspoken/issues/27)
* **write:** the short-piece lint never stands in for write's check and claims steps ([d2c215b](https://github.com/littlebearapps/plainspoken/commit/d2c215b32bbf290540eef555168c7a133e5f3e81)), closes [#23](https://github.com/littlebearapps/plainspoken/issues/23)

## [0.9.0](https://github.com/littlebearapps/plainspoken/compare/v0.8.0...v0.9.0) (2026-10-21)

In short: asks for a long piece now go to write, and write always runs its check and claims steps instead of skipping
them.


### Features

* long-form asks go to write with the full check; write never skips its check and claims steps ([#20](https://github.com/littlebearapps/plainspoken/issues/20)) ([cf1a1a7](https://github.com/littlebearapps/plainspoken/commit/cf1a1a7b9a4d04de4d68d5f8869a33fbb432bc6f))

## [0.8.0](https://github.com/littlebearapps/plainspoken/compare/v0.7.0...v0.8.0) (2026-10-21)

In short: humanize cuts empty claims instead of restating them and writes as the sender would, and write and check
start on more kinds of request, such as text messages, scripts and a single line.


### Features

* tuned humanize, write and check from the pre-v1.0 eval campaign; drafting, long-form and fix eval suites ([#17](https://github.com/littlebearapps/plainspoken/issues/17)) ([5717832](https://github.com/littlebearapps/plainspoken/commit/57178320ca211540c3360041ba28c0cc45786af4))

## [0.7.0](https://github.com/littlebearapps/plainspoken/compare/v0.6.1...v0.7.0) (2026-10-21)

In short: an optional writing nudge and drafting rule, lint after edits in Codex and Hermes Agent, `check -` for text
on stdin, `/plainspoken:setup` to switch the pieces on or off, and a user-wide config file.


### Features

* writing nudge, drafting rule, setup, hooks in Codex and Hermes, humanize trigger fix ([#14](https://github.com/littlebearapps/plainspoken/issues/14)) ([b7e883f](https://github.com/littlebearapps/plainspoken/commit/b7e883f9885d13adb993a6d3e22547e99ac75330))

## [0.6.1](https://github.com/littlebearapps/plainspoken/compare/v0.6.0...v0.6.1) (2026-10-21)

In short: a test-only fix that keeps Trello credentials in your shell out of the tests, plus the `stable` branch,
which holds the latest release and is what Hermes Agent installs follow.


### Bug Fixes

* **tests:** keep shell Trello credentials out of the CLI tests ([ac48aec](https://github.com/littlebearapps/plainspoken/commit/ac48aecf22f8a971fc4150b10cea498055f5e0ff))

## [0.6.0](https://github.com/littlebearapps/plainspoken/compare/v0.5.0...v0.6.0) (2026-10-21)

In short: plainspoken installs in Codex and Hermes Agent as well as Claude Code, with the same skills, agents and
engine. The hooks still ran in Claude Code only.

### Highlights

plainspoken now installs in Codex and Hermes Agent as well as Claude Code. The same skills, agents and engine run in
all three; each new host gets a short note on how to run the skills there (`hosts/codex.md`, `hosts/hermes.md`), and
the judges and checkers run as separate one-shot processes with a fresh context, built by `run.py agent-prompt`.

- **Codex:** `codex plugin marketplace add littlebearapps/lba-plugins`, then `codex plugin add plainspoken@lba-plugins`.
- **Hermes Agent:** `hermes plugins install littlebearapps/plainspoken --enable`. Hermes rates the plugin "caution"
  and asks you to confirm; over SSH or in a script, review the findings and add `--force`.
- Not yet outside Claude Code: the hooks (lint after each edit, publish gate, kaizen nudges) and the install-time
  settings. Run the check yourself before anything goes out. (Lint and the integrity check came to Codex and
  Hermes in 0.7.0)

### Features

* install in Codex and Hermes Agent ([875c23e](https://github.com/littlebearapps/plainspoken/commit/875c23ed872fa74cc1b4662ce0df17dad75138c1))


### Bug Fixes

* clear the Hermes install scan's avoidable HIGH findings ([987afd5](https://github.com/littlebearapps/plainspoken/commit/987afd567b94d623679b78fd11157bd6fea0d444))

## 0.5.0 — first public release (2026-10-20)

In short: the first public release, under the MIT licence, with 11 skills, 4 agents and ruleset 4.3.0.

plainspoken is a Claude Code plugin that helps Claude write like a person: specific, honest and plain, in a stated
voice, with every claim traceable to a saved source. It checks drafts for the patterns that make text read as
machine-written, explains each finding, and only ever fixes by removing the pattern. It runs on Python 3.11+ with the
standard library only. This is the first public release, under the MIT licence.

### Skills

- **check:** lints a draft, sends it to four isolated judges, merges their verdicts and runs up to two removal-only
  fix passes. It ends on PASS, FAIL, UNRESOLVED or INCOMPLETE. A WARN is fixed or kept with a one-line reason that an
  isolated reviewer (JR) accepts or rejects.
- **humanize:** rewrites a draft without a full check, from a pattern catalogue adapted from blader/humanizer (MIT).
- **write, plain-language, voice, copy-audit, register-check, adapt:** draft from notes, make writing plainer (with
  the `cold-reader` agent for long texts), build a voice profile from your own samples, audit buyer-facing copy
  against its evidence, flag a message that reads wrong for its kind, and draft platform versions of a post. Nothing
  is ever posted or sent.
- **claims:** a claim ledger per article. Every number, quote, name and date is pinned to a passage in a source you
  saved; only the isolated `claims-checker` agent can turn the result into PASS.
- **reader-value:** a contract for the reader's benefit before drafting, and an isolated `delivery-checker` agent
  that checks the draft delivers it.
- **kaizen:** improves the checks from your verdicts (see below).

### Engine

- Ruleset 4.3.0: 55 rules. 54 are checked by the lint, a judge or both; rule 3 (Markdown in short-form social) has
  no checker. Some run in shadow (report only) until evidence promotes them. Per-content-type caps for articles and
  social posts, and en-AU, en-GB and en-US word lists.
- Voice profiles in TOML, a shipped neutral default, and per-folder profiles (`[engine] profiles` globs).
- A quotation that runs over several sentences stays quoted, so its words never count against the writer.
- Reports follow a documented contract with a JSON schema, are written atomically and stamp the command that wrote
  them. Every file is listed in `docs/report-contract.md`.
- Hooks: lint-watch after each edit, an integrity check for unsourced statistics in charts, TL;DRs and frontmatter,
  an opt-in publish gate on `git push`, an opt-in session brief, and a quiet kaizen nudge. All are off or silent
  until there's something to say, and hooks add no always-on tokens.

### Judges

- Four isolated judge groups (J1–J4) for the patterns a lint can't settle, plus JR for justifications. Each judge
  reads in a fresh context, returns strict JSON and is bound to the lint's profile and ruleset, so a verdict from an
  older draft or ruleset counts as stale.

### Kaizen

- A local ledger of what the checks flagged and what you did about it: hashes, rule ids and section kinds, with no
  raw text unless you switch excerpts on.
- `calibrate` proposes at most three ruleset or profile changes from that evidence; `mine` compares model drafts
  with a human corpus. Nothing changes until a person posts an `APPROVE:` line and runs `kaizen apply`, which
  refuses a stale proposal and records each change in a changelog (`data/RULESET-CHANGELOG.md` for the ruleset).
- Proposals go to a local file by default, or to a GitHub issue or Trello card if you configure one.

### Evals

- A 232-case golden set with held-out cases, a cross-vendor judge panel, rewrite evals against a no-plugin baseline,
  trigger evals for the skills, ablations of the optional pieces, and a harness for a blind reader test, which
  hasn't been run yet. The unit tests and the golden-set validation are free and run in CI; paid runs need a
  person's OK. Results so far are in `docs/acceptance/p6-evals.md`.

### Tooling

- A leak guard that keeps private names out of the repo. Its list lives outside the repo, hits are logged by
  position rather than by name, and names can be stored as keyed hashes.
- Link, frontmatter, release-version and always-on token-budget checks, and a portable export of the skills.

## Earlier releases (private repository)

plainspoken was built in a private repository before it went public at 0.5.0, so these releases have no public
tags, commits or issues to link to.

### 0.4.0 (2026-10-18)

- Changes to the judges and evals only.
- The golden set's labels were reviewed by a person: 41 cases now carry human labels.
- Rubric fixes for rules 27, 12c and 17.
- Panel replies record which host served them.

### 0.3.0 (2026-10-18)

- The kaizen loop: a local ledger (hashes only by default), with `dismiss`, `uphold`, `missed` and `published` for
  your own verdicts.
- `calibrate` proposes at most 3 changes, and `apply` makes one only after a person approves it. Proposals go to a
  file, a GitHub issue or a Trello card; `mine` compares model drafts with human writing; `report --share` prints
  counts only.
- Stop nudge and backstop hooks for kaizen.
- Evals: a 226-case golden set, a cross-vendor judge panel, rewrite graders, and blind-test and ablation harnesses.

### 0.2.0 (2026-10-14)

- New skills: write, plain-language, voice, copy-audit, register-check, adapt, claims and reader-value, with the
  cold-reader and claims-checker agents.
- Claim ledgers in TOML or JSON, each claim pinned to a saved source and rechecked offline.
- An integrity hook (warn by default), and an opt-in output style and session brief.
- Fixes: the publish gate never blocks a push unless you opt in, and hook state never follows symlinks.

### 0.1.0 (2026-10-11)

- The engine: Python 3.11+, standard library only.
- Ruleset 4.1.0 with 54 rules (5 in shadow, which report only), a default profile, en-AU, en-GB and en-US word
  lists, and a social content type.
- check (lint, then 4 isolated judges, a merge, and fix or justify, with up to 2 fix passes) and humanize
  (removal-only, adapted from blader/humanizer), with the tells-judge agent.
- A lint-watch hook, and an opt-in publish gate on `git push`.
