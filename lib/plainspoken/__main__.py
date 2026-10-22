"""CLI: python3 -m plainspoken {check|profile|config|paths|merge|status|justify|judge-input|agent-prompt|agent-reply|judge-record|anchors|voice-stats|
register-checklist|claims|reader-value|kaizen|eval} …
Exit 0 ok · 1 findings, INCOMPLETE / UNRESOLVED / FAIL (merge), a check or claims result other than PASS (status),
invalid justifications or nothing to review (justify), claims findings, gaps, a failed recheck, a status or checker record other than PASS, a stale ledger
(checker-input, record), reader-value or action-module findings, a delivery record or status other than a
current PASS (every self-check), a stale delivery reply or a contract that doesn't validate (deliver-input,
deliver, status), or a kaizen refusal (no current check or snapshot, no finding, a bad hunk number, capture off, a
ledger that can't be written) · 2 usage or bad input (including a checker or delivery reply that isn't one valid
JSON object, a missing `deliver --reviewer`, a reader-value contract that can't be read, or an unknown kaizen rule,
kind or pattern), or no current / an INCOMPLETE report (justify), an unreadable anchor (anchors, unless
--skip-missing) or too little sample text (voice-stats). `kaizen report` exits 0 even on an empty or damaged
ledger (2 only for a bad --since/--until or [kaizen] config). `kaizen calibrate` and `kaizen review` exit 0 with or
without proposals (2 for a bad --now or config); `kaizen apply` exits 1 when it refuses (no approval, rejected, a
review proposal, a stale proposal (marked superseded outside a dry run), a changed, already-applied or superseded
proposal, an installed plugin's ruleset, a target the proposal doesn't allow) or when the edit is in but the changelog
couldn't be written, and 2 for an unknown proposal id.
`kaizen calibrate` still exits 0 when a proposal couldn't be emitted through the adapter, or was sent but its file
couldn't record the ref (it says so; the next calibrate sends unsent proposals again). `kaizen decisions` never sends:
it exits 0 when proposals are waiting to be sent (it says how many), 1 when any adapter fails (a missing setting or
credential variable, a `gh` or Trello error, a damaged proposal file; nothing is logged for that proposal) or capture is
off, and 2 for bad config. `kaizen mine` exits 0 with or without candidates (they're queued through the file adapter only) and 2
for bad input: no drafts, no model with at least 10 drafts, a draft folder that isn't a model id, no human corpus, no
briefs, a briefs folder that holds a `.heldout` marker, or a file it can't read or lint. `config profile-for` exits 3 when no profile is named for the
file (nothing printed) and 2 for a bad project config or a profile path that doesn't exist. `eval` exit codes are
in evalcli.py. Never a traceback."""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plainspoken import (_util, adapters, calibrate, capture, checker, claims, claims_tools, config, evalcli,
                         extraction, hosts, judges, justify, kaizen, ledger, mining, modules, overrides, pinning, proposals,
                         reader_value, register, report, setup, voice)
from plainspoken.doc import CONTENT_TYPES
from plainspoken.profile import CONTENT_KINDS, Profile, ProfileError
from plainspoken.registry import load_config

# Bad input (a bad profile, unreadable or non-UTF-8 file, a directory, malformed frontmatter YAML) exits 2 with one
# line: exit 1 means "lint BLOCKs, carry on" to /anti-ai-check, so a crash must never look like it.
_INPUT_ERRORS = (ValueError, OSError)  # FrontmatterError and UnicodeDecodeError are both ValueErrors


def _first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


def _input_error(path: Path, e: Exception, verb: str = "check") -> int:
    print(f"plainspoken: can't {verb} {path}: {type(e).__name__}: {_first_line(e)}", file=sys.stderr)
    return 2


def _record_all(args: argparse.Namespace, text: str, root: Path) -> int:
    """`judge-record --all`: J1-J4 from one input in one call (#28). Prints each recorded path; names each group it
    didn't record on stderr, so only those judges run again. Exit 0 = all four recorded, 1 = any not, 2 = I/O."""
    try:
        rows = judges.record_all(args.path, text, args.reports or report.reports_dir_default(root), root)
    except ValueError as e:
        print(f"plainspoken: judge replies not recorded: {_first_line(e)}", file=sys.stderr)
        capture.for_rejected_reply(_first_line(e), root)
        return 1
    except OSError as e:
        return _input_error(args.path, e, "record judge replies for")
    for group, written, reason in rows:
        if written is not None:
            print(written)
        else:
            print(f"plainspoken: {group} reply not recorded: {reason}", file=sys.stderr)
            capture.for_rejected_reply(f"{group}: {reason}", root)
    return 0 if all(written is not None for _, written, _ in rows) else 1


def _same_file(a: Path, b: Path) -> bool:
    try:
        return config.resolve_path(Path(a)) == config.resolve_path(Path(b))
    except (OSError, RuntimeError, ValueError):
        return False


def _profile_ex(args: argparse.Namespace, root: Path) -> tuple[Profile, bool]:
    """The profile for this command: a command with an article path resolves that file's `[engine] profiles`
    entry."""
    target = getattr(args, "path", None)
    return config.resolve_profile_ex(getattr(args, "profile", None), root, os.environ,
                                     getattr(args, "plugin_profile", None),
                                     target if isinstance(target, Path) else None)


def _setup(args: argparse.Namespace, root: Path) -> int:
    wanted = {"nudge": args.nudge, "rule": args.rule, "lint_watch": args.lint_watch}
    wanted = {k: (None if v is None else v == "on") for k, v in wanted.items()}
    if args.status:
        print("\n".join(setup.status(root, os.environ)))
        return 0
    if args.host not in setup.FILE_HOSTS and not any(v is not None for v in wanted.values()) and not args.remove:
        print(setup.paste_text(args.host), end="")
        return 0
    try:
        path, before, after = setup.plan(args.host, args.scope, wanted, root, os.environ, remove=args.remove)
    except (setup.SetupError, OSError) as e:
        print(f"plainspoken: setup: {e}", file=sys.stderr)
        return 2
    if after == before:
        print(f"{path}: nothing to change")
        return 0
    if args.dry_run:
        print(f"{path} would become:\n\n{after or '(deleted: nothing left in it)'}")
        return 0
    setup.apply(path, after)
    print(f"{path}: updated")
    print("\n".join(setup.status(root, os.environ)))
    if args.host in setup.AFTER:
        print(setup.AFTER[args.host])
    return 0


STDIN_SOCIAL_WORDS = 300  # a stdin draft under this many words lints as social unless --content-type says otherwise


def _check_stdin(args: argparse.Namespace, root: Path) -> int:
    """Lint a draft read from stdin: a chat reply, a text or a post that never becomes a file. Nothing is saved and
    no kaizen event is recorded (there is no document to key them to)."""
    if args.out is not None or args.reports is not None:
        print("plainspoken: check - (stdin) saves nothing; drop --out/--reports, or write the draft to a file",
              file=sys.stderr)
        return 2
    text = sys.stdin.read()
    if not text.strip():
        print("plainspoken: can't check stdin: the draft is empty", file=sys.stderr)
        return 2
    content_type = args.content_type or ("social" if len(text.split()) < STDIN_SOCIAL_WORDS else "article")
    with tempfile.TemporaryDirectory(prefix="plainspoken-stdin-") as tmp:
        draft = Path(tmp) / "draft.md"
        draft.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        args.path = None  # no file: the project's [engine] profiles entries don't apply
        try:
            prof = _profile(args, root)
            lint = report.run_lint(draft, prof, content_type, load_config())
        except _INPUT_ERRORS as e:
            return _input_error(Path("<stdin>"), e)
    lint["article"] = "<stdin>"
    print(json.dumps(lint, indent=2, ensure_ascii=False) if args.json else report.summarise(lint))
    return 1 if report.lint_status(lint) == "BLOCK" else 0


def _profile(args: argparse.Namespace, root: Path) -> Profile:
    return _profile_ex(args, root)[0]


def _profile_summary(p: Profile, cfg, plugin_default: bool = False) -> str:
    over = ", ".join(f"{k}={v}" for k, v in sorted(p.thresholds.items())) or "none"
    tag = " (plugin default)" if plugin_default else ""
    deprecated = sorted(r.id for r in cfg.rules.values() if r.status == "deprecated" and r.applies_to(p))
    return "\n".join([
        f"plainspoken profile: {p.name}{tag} ({p.source})",
        f"locale {p.locale} · flags: {', '.join(sorted(p.flags)) or 'none'} · ruleset {cfg.version}",
        f"threshold overrides: {over}",
        f"extra bans: {len(p.extra_bans)} · disabled rules: {', '.join(sorted(p.rules_disabled)) or 'none'}"
        f" · deprecated rules: {', '.join(deprecated) or 'none'}",
        f"calibration notes: {p.calibration_notes or 'none'}",
        *voice.summary_lines(p),
    ])


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as e:  # last resort: a traceback exits 1, which /anti-ai-check reads as "BLOCK, carry on"
        print(f"plainspoken: internal error: {type(e).__name__}: {_first_line(e)}", file=sys.stderr)
        return 2


def _main(argv: list[str] | None) -> int:
    ap = argparse.ArgumentParser(prog="plainspoken")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="deterministic lint of one article, or of a draft on stdin with `-`")
    c.add_argument("path", type=Path, help="the article, or - to lint a draft read from stdin (nothing is saved)")
    c.add_argument("--profile")
    c.add_argument("--plugin-profile")
    c.add_argument("--content-type", choices=CONTENT_TYPES,
                   help="default: article; for stdin, social under 300 words, else article")
    c.add_argument("--json", action="store_true")
    c.add_argument("--out", type=Path)
    c.add_argument("--reports", type=Path)
    c.add_argument("--no-save", action="store_true")
    c.add_argument("--no-record", action="store_true",
                   help="a read-only look: print the lint, save no report and record no kaizen event or snapshot")
    pr = sub.add_parser("profile", help="print the resolved profile summary, or its stamps with --json")
    pr.add_argument("path", nargs="?", type=Path, help="the article the profile is for (its [engine] profiles entry)")
    pr.add_argument("--profile")
    pr.add_argument("--plugin-profile")
    pr.add_argument("--voice", action="store_true", help="print the voice sections the skills draft and check from")
    pr.add_argument("--type", help="with --voice: only this content type's blend and formatting "
                                   f"({', '.join(CONTENT_KINDS)})")
    pr.add_argument("--json", action="store_true", help="print the stamps a report is bound to: name, path, "
                                                        "profile_sha256, ruleset_version, root")
    co = sub.add_parser("config", help="what the project config resolves to")
    cos = co.add_subparsers(dest="config_cmd", required=True)
    pf = cos.add_parser("profile-for", help="print the profile for one file (PLAINSPOKEN_PROFILE, else the first "
                                             "[engine] profiles match, else [engine] profile); exit 3 when none")
    pf.add_argument("file", type=Path)
    an = sub.add_parser("anchors", help="print the profile's anchor passages, optionally for one tag")
    an.add_argument("--tag")
    an.add_argument("--limit", type=int, default=3)
    an.add_argument("--skip-missing", action="store_true",
                    help="skip an anchor whose file can't be read (one line each) instead of exiting 2")
    an.add_argument("--profile")
    an.add_argument("--plugin-profile")
    rc = sub.add_parser("register-checklist", help="print the register-check items for one message kind")
    rc.add_argument("--kind", required=True)
    rc.add_argument("--register")
    rc.add_argument("--profile")
    rc.add_argument("--plugin-profile")
    vs = sub.add_parser("voice-stats", help="measure sentence rhythm in samples; prints a [rhythm] table")
    vs.add_argument("paths", nargs="+", type=Path)
    ln = sub.add_parser("length", help="count characters (as a reader sees them), words and lines in a draft")
    ln.add_argument("path", type=Path)
    pa = sub.add_parser("paths", help="print every report-file path for an article")
    pa.add_argument("path", type=Path)
    pa.add_argument("--reports", type=Path)
    m = sub.add_parser("merge", help="combine lint + judge verdicts; prove coverage")
    m.add_argument("path", type=Path)
    m.add_argument("--reports", type=Path)
    m.add_argument("--profile")
    m.add_argument("--plugin-profile")
    st = sub.add_parser("status", help="the last saved check and claims status lines for a draft, the claims "
                                       "that need the owner, its word count and its reader-value contract path, for a report to quote (runs and "
                                       "writes nothing)")
    st.add_argument("path", type=Path)
    st.add_argument("--reports", type=Path)
    st.add_argument("--ledger", type=Path)
    st.add_argument("--profile")
    st.add_argument("--plugin-profile")
    j = sub.add_parser("justify", help="fix or justify: a justification template, or the JR judge's input")
    j.add_argument("path", type=Path)
    j.add_argument("--reports", type=Path)
    mode = j.add_mutually_exclusive_group(required=True)
    mode.add_argument("--template", action="store_true",
                      help="a <stem>.justify.json skeleton for the current report's unresolved WARN rules")
    j.add_argument("--write", action="store_true",
                   help="with --template: write the keyed <stem>.justify.json atomically and print its path")
    mode.add_argument("--review-input", action="store_true",
                      help="validate <stem>.justify.json and print the JR judge's input")
    j.add_argument("--profile", help="with --review-input: the voice profile whose calibration notes the JR judge gets")
    j.add_argument("--plugin-profile")
    ji = sub.add_parser("judge-input", help="print one JSON judge-input object per group, J1 to J4")
    ji.add_argument("path", type=Path)
    ji.add_argument("--reports", type=Path)
    ji.add_argument("--profile")
    ji.add_argument("--plugin-profile")
    ag = sub.add_parser("agent-prompt", help="print an agent's self-contained prompt with stdin as its input, for "
                                             "hosts without plugin agents (Codex, Hermes)")
    ag.add_argument("name", choices=list(hosts.AGENTS))
    ag.add_argument("--line", type=int, help="use only the Nth non-blank input line (1 = J1 from judge-input)")
    sub.add_parser("agent-reply", help="cut the JSON object out of an agent's output on stdin (host CLIs add a "
                                       "session line or a fence); the record step still validates it")
    jr = sub.add_parser("judge-record", help="record a judge's JSON reply, or J1-J4 at once with --all (from --from "
                                             "FILE, else stdin)")
    jr.add_argument("path", type=Path)
    which = jr.add_mutually_exclusive_group(required=True)
    which.add_argument("--group", choices=[*judges.GROUPS, "JR"])
    which.add_argument("--all", action="store_true",
                       help="record J1-J4 from one input: their replies one after another, or one JSON list")
    jr.add_argument("--reports", type=Path)
    jr.add_argument("--from", dest="reply_file", type=Path,
                    help="read the reply from this file; the `reply` path from `paths` is deleted afterwards, "
                         "any other file is kept")
    su = sub.add_parser("setup", help="turn the writing nudge, the drafting rule and lint after edits on or off for "
                                      "one host (or print the text to paste into claude.ai or ChatGPT)")
    su.add_argument("--host", required=True, choices=setup.HOSTS)
    su.add_argument("--scope", choices=("project", "user"), default="project",
                    help="project: .plainspoken/config.toml here; user: ~/.config/plainspoken/config.toml")
    for name, what in (("nudge", "the writing nudge"), ("rule", "the drafting rule (Claude Code)"),
                       ("lint-watch", "lint after each edit")):
        su.add_argument(f"--{name}", choices=("on", "off"), help=f"{what}; unset leaves it as it is")
    su.add_argument("--dry-run", action="store_true", help="print the change without writing it")
    su.add_argument("--remove", action="store_true", help="delete every setting setup wrote to this file first")
    su.add_argument("--status", action="store_true", help="print what is on now")
    _claims_parser(sub)
    _reader_value_parser(sub)
    _kaizen_parser(sub)
    evalcli.add_parser(sub)
    args = ap.parse_args(argv)
    root = config.project_root(Path.cwd())  # run from anywhere in the project: reports and config live at its root

    if args.cmd == "setup":
        return _setup(args, root)
    if args.cmd == "check" and str(args.path) == "-":
        return _check_stdin(args, root)
    if args.cmd == "check":
        args.content_type = args.content_type or "article"
        try:
            prof = _profile(args, root)
            cfg = load_config()
            lint = report.run_lint(args.path, prof, args.content_type, cfg)
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e)
        payload = json.dumps(lint, indent=2, ensure_ascii=False)
        paths = report.report_paths(args.path, args.reports or report.reports_dir_default(root), root)
        target = args.out
        if target is None and not (args.no_save or args.no_record):
            target = paths["lint"]
        # The snapshot and the fixed diff pair with <key>.lint.json, so they run only when that's what was saved.
        keyed = target is not None and _same_file(target, paths["lint"])
        if keyed and args.no_record:  # <key>.lint.json pairs with the snapshot, which --no-record leaves alone
            print(f"plainspoken: --no-record saves no report: --out {target} is this article's lint report; drop "
                  f"--out or name another file", file=sys.stderr)
            return 2
        previous = report.read_json(paths["lint"]) if keyed else None  # before it's overwritten
        if target:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if keyed:  # the gate and merge read it: never half a file. --out elsewhere may be a pipe or device.
                    report.write_atomic(target, payload + "\n")
                else:
                    target.write_text(payload + "\n", encoding="utf-8")
            except OSError as e:
                return _input_error(target, e, "write")
        if not args.no_record:
            capture.for_check(lint, args.path, prof, cfg, root, previous=previous,
                              snapshot=paths["checked"] if keyed else None, reports=paths["checked"].parent)
        print(payload if args.json else report.summarise(lint))
        return 1 if report.lint_status(lint) == "BLOCK" else 0
    if args.cmd == "profile":
        if args.type is not None and not args.voice:
            print("plainspoken: --type goes with --voice", file=sys.stderr)
            return 2
        if args.json and args.voice:
            print("plainspoken: --json doesn't go with --voice", file=sys.stderr)
            return 2
        if args.type is not None and args.type not in CONTENT_KINDS:
            print(f"plainspoken: unknown --type {args.type!r} (expected article, page, email or social)",
                  file=sys.stderr)
            return 2
        try:
            prof, plugin_default = _profile_ex(args, root)
        except _INPUT_ERRORS as e:
            print(f"plainspoken: {_first_line(e)}", file=sys.stderr)
            return 2
        if args.voice:
            print("\n".join(voice.voice_lines(prof, args.type)))
            return 0
        if args.json:  # the stamps `check` and `merge` bind a report to (docs/report-contract.md)
            try:
                version = load_config().version
            except _INPUT_ERRORS as e:
                print(f"plainspoken: {_first_line(e)}", file=sys.stderr)
                return 2
            print(json.dumps({"name": prof.name, "path": prof.source, "profile_sha256": prof.sha256,
                              "ruleset_version": version, "root": str(root)}, indent=2))
            return 0
        try:
            gate = "{} ({})".format(*config.gate_strictness(root, os.environ))
        except _INPUT_ERRORS as e:
            gate = f"can't read ({_first_line(e)})"
        print(_profile_summary(prof, load_config(), plugin_default) + f"\ngate: {gate}")
        return 0
    if args.cmd == "config":
        try:
            value = os.environ.get("PLAINSPOKEN_PROFILE") or config.profile_for(args.file, root)
        except _INPUT_ERRORS as e:  # ConfigError
            print(f"plainspoken: {_first_line(e)}", file=sys.stderr)
            return 2
        if not value:
            print(f"plainspoken: no profile for {args.file} in the project config (pass --plugin-profile as usual)",
                  file=sys.stderr)
            return 3
        if config.is_profile_path(value) and not Path(value).is_file():  # a path that can't load fails every check
            print(f"plainspoken: profile {value} doesn't exist", file=sys.stderr)
            return 2
        print(value)
        return 0
    if args.cmd == "paths":
        d = args.reports or report.reports_dir_default(root)
        try:
            ledger = str(claims.ledger_path_for(args.path, root))
            sources = str(root / config.claims_settings(root)["sources_dir"])
        except _INPUT_ERRORS as e:  # ConfigError: a malformed [claims] section. `paths` is on the anti-AI check's
            ledger = sources = f"(unresolved: {_first_line(e)})"  # path, so it never fails for a claims setting.
        print(json.dumps({"key": report.report_key(args.path, root),
                          **{k: str(v) for k, v in report.report_paths(args.path, d, root).items()},
                          "ledger": ledger, "sources": sources}, indent=2))
        return 0
    if args.cmd == "claims":
        return _claims(args, root)
    if args.cmd == "reader-value":
        return _reader_value(args, root)
    if args.cmd == "kaizen":
        return _kaizen(args, root)
    if args.cmd == "eval":
        return evalcli.run(args)
    if args.cmd == "merge":
        reports_dir = args.reports or report.reports_dir_default(root)
        try:
            prof = _profile(args, root)
            merged = report.merge(args.path, reports_dir, prof, cwd=root)
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e)
        capture.for_merge(merged, args.path, prof, root)
        print("\n".join(report.merge_lines(merged)))
        return 0 if merged["status"] == "PASS" else 1
    if args.cmd == "status":
        return _draft_status(args, root)
    if args.cmd == "judge-input":
        try:
            items = judges.judge_input(args.path, _profile(args, root),
                                       args.reports or report.reports_dir_default(root), root)
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e, "prepare judge input for")
        for item in items:
            print(json.dumps(item, ensure_ascii=False))
        return 0
    if args.cmd == "agent-prompt":
        try:
            sys.stdout.write(hosts.agent_prompt(args.name, sys.stdin.read(), args.line))
        except _INPUT_ERRORS as e:
            print(f"plainspoken: can't build the {args.name} prompt: {_first_line(e)}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "agent-reply":
        try:
            sys.stdout.write(hosts.agent_reply(sys.stdin.read()))
        except ValueError as e:
            print(f"plainspoken: no agent reply: {_first_line(e)}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "judge-record":
        if args.reply_file is not None:
            # A file, not a heredoc: Claude Code's shell check stops JSON on a command line (docs/acceptance/p2-e2e.md).
            try:
                text = args.reply_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                print(f"plainspoken: can't read the judge reply {args.reply_file}: {type(e).__name__}: {_first_line(e)}",
                      file=sys.stderr)
                return 2
            scratch = report.report_paths(args.path, args.reports or report.reports_dir_default(root),
                                          root)["reply"]
            if args.reply_file.resolve() == scratch.resolve():
                # The scratch reply is consumed even when it's rejected (by design): the retry's Write starts fresh.
                try:
                    args.reply_file.unlink(missing_ok=True)
                except OSError:
                    pass
        else:
            text = sys.stdin.read()
        if args.all:
            return _record_all(args, text, root)
        try:
            written = judges.record_reply(args.path, args.group, text,
                                          args.reports or report.reports_dir_default(root), root)
        except ValueError as e:
            print(f"plainspoken: judge reply not recorded: {_first_line(e)}", file=sys.stderr)
            capture.for_rejected_reply(_first_line(e), root)
            return 1
        except OSError as e:
            return _input_error(args.path, e, "record a judge reply for")
        print(written)
        return 0
    if args.cmd == "anchors":
        if args.limit < 1:
            print(f"plainspoken: --limit must be 1 or more (got {args.limit})", file=sys.stderr)
            return 2
        skipped: list[str] = []
        try:
            prof = _profile(args, root)
            if args.skip_missing:
                found, skipped = voice.anchors_lenient(prof, args.tag, args.limit)
            else:
                found = voice.anchors_for(prof, args.tag, args.limit)
        except _INPUT_ERRORS as e:  # VoiceError and ProfileError are ValueErrors
            print(f"plainspoken: {_first_line(e)}", file=sys.stderr)
            return 2
        for message in skipped:
            print(f"(skipped {message})")
        if not found:
            print(f"(no anchors tagged {args.tag!r} in profile {prof.name})" if args.tag
                  else f"(no anchors in profile {prof.name})")
            return 0
        for a, text in found:
            print(f"--- anchor {a.id} ({', '.join(a.tags)}) from {a.source or a.path or 'the profile'}\n{text}\n")
        return 0
    if args.cmd == "register-checklist":
        try:
            items = register.checklist(args.kind, _profile(args, root), args.register)
        except _INPUT_ERRORS as e:  # ProfileError is a ValueError
            print(f"plainspoken: {_first_line(e)}", file=sys.stderr)
            return 2
        for i in items:
            print(f"{i['id']} {i['title']}: {i['ask']} Flag when: {i['flag_when']}")
        return 0
    if args.cmd == "length":
        try:
            raw = args.path.read_text(encoding="utf-8")
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e, "measure")
        text = raw.rstrip("\n")
        print(f"chars {_util.graphemes(text)} · words {len(text.split())} · lines {len(text.splitlines())}")
        return 0
    if args.cmd == "voice-stats":
        try:
            print(voice.stats_toml(voice.stats(args.paths)), end="")
        except _INPUT_ERRORS as e:
            print(f"plainspoken: {_first_line(e)}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "justify":
        notes = None
        if args.review_input:
            try:
                notes = _profile(args, root).calibration_notes or None
            except _INPUT_ERRORS as e:
                return _input_error(args.path, e, "resolve the profile for")
        if args.write and not args.template:
            print("plainspoken: --write goes with --template", file=sys.stderr)
            return 2
        return _justify(args.path, args.template, args.reports, notes, args.write, root)
    return 2


def _claims_parser(sub) -> None:
    cl = sub.add_parser("claims", help="claim ledgers: hash, stamp, validate, candidates, gaps, pin, recheck, "
                                       "scaffold, status, checker-input, record")
    cs = cl.add_subparsers(dest="claims_cmd", required=True)
    h = cs.add_parser("hash", help="print the article's sha256:<hex> (the ledger's source_content_hash)")
    h.add_argument("path", type=Path)
    h.add_argument("--stamp", action="store_true",
                   help='also print checked_at = "<now, ISO 8601 with offset>" (`claims stamp` writes both for you)')
    sp = cs.add_parser("stamp", help="write the article's hash, checked_at and checked_by into its ledger "
                                     "(refuses until coverage is complete and no gap is open)")
    sp.add_argument("path", type=Path)
    sp.add_argument("--ledger", type=Path)
    sp.add_argument("--by", default="claims skill", help='checked_by (default: "claims skill")')
    v = cs.add_parser("validate", help="validate a ledger; one finding per line")
    v.add_argument("ledger", type=Path)
    v.add_argument("--root", type=Path, help="the project root its source_file is relative to (default: found)")
    ca = cs.add_parser("candidates", help="the deterministic claim candidates in an article")
    ca.add_argument("path", type=Path)
    ca.add_argument("--json", action="store_true")
    g = cs.add_parser("gaps", help="value and quote candidates the ledger doesn't hold")
    g.add_argument("path", type=Path)
    g.add_argument("--ledger", type=Path)
    g.add_argument("--json", action="store_true")
    p = cs.add_parser("pin", help="locate a passage verbatim in a saved source; print a TOML binding fragment")
    p.add_argument("--source", type=Path, required=True,
                   help="the saved source text, under [claims] sources_dir (default .plainspoken/sources/)")
    p.add_argument("--passage", required=True, help="the supporting passage, copied verbatim from the source")
    p.add_argument("--retrieved-at", help="when the source was retrieved (default: now, ISO 8601)")
    p.add_argument("--snapshot-path", help="project-relative path under sources_dir recorded as source_snapshot "
                                           "(default: --source's project-relative path)")
    p.add_argument("--article", type=Path,
                   help="the article the claim is in: a --source or --snapshot-path that is this file is refused")
    p.add_argument("--additional", action="store_true",
                   help="print an additional_passages item instead (no source_snapshot)")
    p.add_argument("--source-url", help="with --additional: the https:// page this passage is on, if not the source")
    p.add_argument("--locator", help="with --additional: where on the page the passage is")
    r = cs.add_parser("recheck", help="recheck every pinned passage against its saved source, offline")
    r.add_argument("ledger", type=Path)
    r.add_argument("--root", type=Path, help="the project root snapshots are relative to (default: found)")
    s = cs.add_parser("scaffold", help="write a starter ledger: every candidate a blocking claim")
    s.add_argument("path", type=Path)
    s.add_argument("--out", type=Path, help="the .toml ledger to write (default: the article's ledger path)")
    s.add_argument("--id-prefix", help="claim id prefix (default: the article stem, upper-cased)")
    st = cs.add_parser("status", help="PASS, INCOMPLETE or BLOCKED; writes <key>.claims.json")
    st.add_argument("path", type=Path)
    st.add_argument("--ledger", type=Path)
    st.add_argument("--reports", type=Path)
    st.add_argument("--json", action="store_true")
    ci = cs.add_parser("checker-input", help="print the claims-checker agent's input (refuses a stale ledger)")
    ci.add_argument("path", type=Path)
    ci.add_argument("--ledger", type=Path)
    rr = cs.add_parser("record", help="verify the claims-checker's reply; write <key>.claims-check.json")
    rr.add_argument("path", type=Path)
    rr.add_argument("--from", dest="reply_file", type=Path, required=True, help="the agent's reply, saved to a file")
    rr.add_argument("--ledger", type=Path)
    rr.add_argument("--reports", type=Path)


def _reader_value_parser(sub) -> None:
    rv = sub.add_parser("reader-value", help="reader-value contracts, action modules and the delivery gate: "
                                             "validate, modules, template, deliver-input, deliver")
    rs = rv.add_subparsers(dest="rv_cmd", required=True)
    v = rs.add_parser("validate", help="validate a contract (.toml, .json, or a markdown file's "
                                       "'## Reader Value Contract' block); one finding per line")
    v.add_argument("path", type=Path)
    m = rs.add_parser("modules", help="check an article's <!-- module:NAME --> blocks; one finding per line")
    m.add_argument("path", type=Path)
    rs.add_parser("template", help="print a starter contract (TOML)")
    contract_help = "the draft's contract (default: .plainspoken/reader-value/<draft stem>.reader-value.toml)"
    di = rs.add_parser("deliver-input", help="print the delivery-checker agent's input (refuses a contract that "
                                             "doesn't validate)")
    di.add_argument("path", type=Path)
    di.add_argument("--contract", type=Path, help=contract_help)
    dl = rs.add_parser("deliver", help="verify the delivery-checker's reply; write <key>.delivery.json")
    dl.add_argument("path", type=Path)
    dl.add_argument("--from", dest="reply_file", type=Path, required=True, help="the reply, saved to a file")
    dl.add_argument("--contract", type=Path, help=contract_help)
    dl.add_argument("--reports", type=Path)
    dl.add_argument("--reviewer", required=True, choices=reader_value.REVIEWERS,
                    help="who wrote the reply: delivery-checker (the isolated agent) or self-check (the writer's own "
                         "reading: recorded, never a PASS). Required: there's no default")
    ds = rs.add_parser("status", help="PASS, FAIL, INCOMPLETE or STALE: the delivery record read against the draft, "
                                      "contract and rubric now")
    ds.add_argument("path", type=Path)
    ds.add_argument("--contract", type=Path, help=contract_help)
    ds.add_argument("--reports", type=Path)
    ds.add_argument("--json", action="store_true")


def _contract_error(path: Path, e: Exception, verb: str) -> int:
    """`_input_error`, except that a ContractError already names the file: it's printed once, not twice."""
    if isinstance(e, reader_value.ContractError):
        print(f"plainspoken: can't {verb} the contract: ContractError: {_first_line(e)}", file=sys.stderr)
        return 2
    return _input_error(path, e, verb)


def _reader_value(args: argparse.Namespace, root: Path) -> int:
    cmd = args.rv_cmd
    if cmd == "validate":
        try:
            contract = reader_value.load_contract(args.path)
            findings = reader_value.validate(contract, reader_value.cta_phrases(root),
                                             reader_value.shipped_vague_phrases())
        except _INPUT_ERRORS as e:  # ContractError, ConfigError and SchemaError are ValueErrors
            return _contract_error(args.path, e, "validate")
        for f in findings:
            print(f"{f['severity']}: {f['message']}")
        if not findings:
            print(f"reader-value: {args.path} is valid (no findings)")
        return 1 if findings else 0
    if cmd == "modules":
        try:
            found = modules.check(args.path.read_text(encoding="utf-8"))
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e, "check the modules in")
        for f in found:
            print(f"line {f['line']}: {f['message']}")
        if not found:
            print(f"modules: {args.path} has no findings")
        return 1 if found else 0
    if cmd == "template":
        try:
            print(reader_value.TEMPLATE.read_text(encoding="utf-8"), end="")
        except _INPUT_ERRORS as e:
            return _input_error(reader_value.TEMPLATE, e, "read")
        return 0
    if cmd == "deliver-input":
        contract = args.contract or reader_value.default_contract(args.path, root)
        try:
            block = reader_value.delivery_input(args.path, contract, root)
        except reader_value.ContractNotReady as e:
            print(f"plainspoken: delivery reviewer not started: {e}", file=sys.stderr)
            return 1
        except _INPUT_ERRORS as e:
            return _contract_error(args.path, e, "prepare the delivery input for")
        print(json.dumps(block, indent=2, ensure_ascii=False))
        return 0
    if cmd == "deliver":
        return _deliver(args, root)
    if cmd == "status":
        return _delivery_status(args, root)
    return 2


def _delivery_status(args: argparse.Namespace, root: Path) -> int:
    contract = args.contract or reader_value.default_contract(args.path, root)
    try:
        record_path = report.report_paths(args.path, args.reports or report.reports_dir_default(root),
                                          root)["delivery"]
        st = reader_value.delivery_status(args.path, contract, record_path, root)
    except _INPUT_ERRORS as e:
        return _contract_error(args.path, e, "report the delivery status of")
    if args.json:
        print(json.dumps(st, indent=2, ensure_ascii=False))
    else:
        print("\n".join([f"delivery: {st['status']}", *(f"  {r}" for r in st["reasons"])]))
    return 0 if st["status"] == "PASS" else 1


def _deliver(args: argparse.Namespace, root: Path) -> int:
    try:
        text = args.reply_file.read_text(encoding="utf-8")
    except _INPUT_ERRORS as e:
        return _input_error(args.reply_file, e, "read the delivery reply")
    contract = args.contract or reader_value.default_contract(args.path, root)
    try:
        record_path = report.report_paths(args.path, args.reports or report.reports_dir_default(root),
                                          root)["delivery"]
        display = {"article": claims_tools.display_path(args.path, root),
                   "contract": claims_tools.display_path(contract, root)}
    except _INPUT_ERRORS as e:
        return _input_error(args.path, e, "record the delivery reply for")
    reviewer = args.reviewer
    try:
        rec = reader_value.record_delivery(args.path, contract, text, record_path, display, root, reviewer)
    except reader_value.StaleDeliveryReply as e:  # nothing written; any earlier record is left as it is
        print(f"plainspoken: delivery reply not recorded: {e}", file=sys.stderr)
        return 1
    except reader_value.ContractNotReady as e:  # recorded as INCOMPLETE
        print(f"plainspoken: delivery gate can't run ({record_path} now says INCOMPLETE): {e}", file=sys.stderr)
        return 1
    except reader_value.DeliveryReplyError as e:  # recorded as INCOMPLETE, so no earlier PASS outlives it
        print(f"plainspoken: delivery reply rejected ({record_path} now says INCOMPLETE): {_first_line(e)}",
              file=sys.stderr)
        return 2
    except _INPUT_ERRORS as e:
        return _contract_error(args.path, e, "record the delivery reply for")
    head = f"delivery: {rec['result']}"
    if reviewer == "self-check":
        head += f" (self-check: the writer's own reading is {rec['reading']}; only the isolated reviewer passes)"
    print(f"{head} · {len(rec['items'])} item(s): {rec['failed']} failed · {rec['unverified_evidence']} with "
          f"unverified evidence · {len(rec['module_findings'])} module finding(s)"
          + (" · prose outside the JSON ignored" if rec["reply_had_prose"] else ""))
    for it in rec["items"]:
        mark = " [evidence unverified: not verbatim in the draft]" if it["evidence_verified"] is False else ""
        quote = it.get("evidence") if it.get("evidence") is not None else it.get("why")
        print(f"  {it['verdict']} {it['item']}: {str(quote)[:120]}{mark}")
    for f in rec["module_findings"]:
        print(f"  module line {f['line']}: {f['message']}")
    print(f"wrote {record_path}")
    return 0 if rec["result"] == "PASS" else 1


def _usage(message: str) -> int:
    print(f"plainspoken: {message}", file=sys.stderr)
    return 2


def _candidate_line(c: dict) -> str:
    return f"{c['line']} {c['surface']} {c['kind']} {c['value']}: {c['text']}"


def _claims(args: argparse.Namespace, root: Path) -> int:
    cmd = args.claims_cmd
    if cmd == "hash":
        try:
            print(claims.article_hash(args.path))
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e, "hash")
        if args.stamp:
            print(f'checked_at = "{_util.now_iso()}"')
        return 0
    if cmd == "stamp":
        return _stamp(args, root)
    if cmd == "validate":
        try:
            findings = claims.validate_ledger(args.ledger, args.root or root)
        except _INPUT_ERRORS as e:  # LedgerError names the file
            return _input_error(args.ledger, e, "validate")
        for f in findings:
            print(f"{f['severity']} {f['claim_id'] or '-'}: {f['message']}")
        if not findings:
            print(f"claims: {args.ledger} is valid and fresh (no findings)")
        return 1 if any(f["severity"] in ("error", "blocking") for f in findings) else 0
    if cmd == "candidates":
        try:
            cands = extraction.extract_candidates(args.path.read_text(encoding="utf-8"),
                                                  extraction.platform_names(root))
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e, "extract candidates from")
        print(json.dumps(cands, indent=2, ensure_ascii=False) if args.json
              else "\n".join(_candidate_line(c) for c in cands) or "(no candidates)")
        return 0
    if cmd == "gaps":
        try:
            ledger = args.ledger or claims.ledger_path_for(args.path, root)
            text = args.path.read_text(encoding="utf-8")
            gaps = extraction.value_gaps(text, claims.load_ledger(ledger), extraction.platform_names(root))
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e, "find the gaps in")
        print(json.dumps(gaps, indent=2, ensure_ascii=False) if args.json
              else "\n".join(_candidate_line(c) for c in gaps) or "claims: no gaps")
        return 1 if gaps else 0
    if cmd == "pin":
        return _pin(args, root)
    if cmd == "recheck":
        try:
            results = pinning.recheck(claims.load_ledger(args.ledger), args.root or root)
        except _INPUT_ERRORS as e:
            return _input_error(args.ledger, e, "recheck")
        for res in results:
            print(f"{res['claim_id'] or '-'} {res['result']}: {res['detail']}")
        if not results:
            print("claims: no pinned passages to recheck")
        return 1 if any(res["result"] not in ("ok", "unchecked") for res in results) else 0
    if cmd == "scaffold":
        return _scaffold(args, root)
    if cmd == "status":
        return _status(args, root)
    if cmd == "checker-input":
        try:
            ledger = args.ledger or claims.ledger_path_for(args.path, root)
            block = checker.checker_input(args.path, ledger, root)
        except checker.StaleLedger as e:
            print(f"plainspoken: checker not started: {e}", file=sys.stderr)
            return 1
        except _INPUT_ERRORS as e:
            return _input_error(args.path, e, "prepare the checker input for")
        print(json.dumps(block, indent=2, ensure_ascii=False))
        return 0
    if cmd == "record":
        return _record(args, root)
    return 2


def _write_claims_report(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    report.write_atomic(path, payload + "\n")


def _status(args: argparse.Namespace, root: Path) -> int:
    try:
        check_path = report.report_paths(args.path, args.reports or report.reports_dir_default(root), root)
    except _INPUT_ERRORS as e:
        return _input_error(args.path, e, "report the claims status of")
    ledger = args.ledger
    try:
        ledger = ledger or claims.ledger_path_for(args.path, root)
        rep = claims_tools.status_report(args.path, ledger, root, check_path["claims-check"],
                                         extraction.platform_names(root))
    except _INPUT_ERRORS as e:  # rewrite <key>.claims.json first, so an earlier PASS can't linger
        try:
            _write_claims_report(check_path["claims"], json.dumps(
                claims_tools.unreported(args.path, ledger, root, e), indent=2, ensure_ascii=False))
        except OSError:
            pass  # the bad-input message below is the one to show
        return _input_error(args.path, e, "report the claims status of")
    payload = json.dumps(rep, indent=2, ensure_ascii=False)
    try:
        _write_claims_report(check_path["claims"], payload)
    except OSError as e:
        return _input_error(check_path["claims"], e, "write")
    print(payload if args.json else "\n".join([f"claims: {rep['status']}", *(f"  {r}" for r in rep["reasons"])]))
    return 0 if rep["status"] == "PASS" else 1


def _draft_status(args: argparse.Namespace, root: Path) -> int:
    """`status`: what a report quotes, read back from saved files. Neither result can come from memory, and a step
    that never ran shows as INCOMPLETE. Exit 0 only when both say PASS."""
    reports_dir = args.reports or report.reports_dir_default(root)
    try:
        if not args.path.is_file():
            raise FileNotFoundError(f"no such file: {args.path}")
        prof = _profile(args, root)
        check_status, check_lines = report.saved_check(args.path, reports_dir, prof, root)
        words = report.word_count(args.path, prof)
    except _INPUT_ERRORS as e:
        return _input_error(args.path, e, "report the status of")
    ledger = args.ledger
    try:
        ledger = ledger or claims.ledger_path_for(args.path, root)
        rep = claims_tools.status_report(args.path, ledger, root,
                                         report.report_paths(args.path, reports_dir, root)["claims-check"],
                                         extraction.platform_names(root))
    except _INPUT_ERRORS as e:
        rep = {"status": "INCOMPLETE", "reasons": [f"can't report: {type(e).__name__}: {_first_line(e)}"]}
    try:  # read from the ledger, so a report can't say "none" while a claim waits on the owner (#45)
        if ledger is None:
            raise FileNotFoundError("no ledger")
        owner = claims.needs_owner(claims.load_ledger(ledger))
        owner_lines = [f"needs the owner: {len(owner) or 'none'}", *(f"  {o}" for o in owner)]
    except _INPUT_ERRORS:
        owner_lines = ["needs the owner: unknown (no readable ledger)"]
    contract = reader_value.default_contract(args.path, root)
    shown = claims_tools.display_path(contract, root)
    counted = f"words: {words} (body text; headings, tables, code and numbers not counted)"  # #63: say what it counts
    print("\n".join([f"check: {check_lines[0]}", *check_lines[1:], f"claims: {rep['status']}",
                     *(f"  {r}" for r in rep["reasons"]), *owner_lines, counted,
                     f"reader-value contract: {shown}" + ("" if contract.is_file() else " (missing)")]))
    return 0 if check_status == rep["status"] == "PASS" else 1


def _record(args: argparse.Namespace, root: Path) -> int:
    try:
        text = args.reply_file.read_text(encoding="utf-8")
    except _INPUT_ERRORS as e:
        return _input_error(args.reply_file, e, "read the checker reply")
    try:
        ledger = args.ledger or claims.ledger_path_for(args.path, root)
        check_path = report.report_paths(args.path, args.reports or report.reports_dir_default(root),
                                         root)["claims-check"]
        display = {"article": claims_tools.display_path(args.path, root),
                   "ledger": claims_tools.display_path(ledger, root)}
    except _INPUT_ERRORS as e:
        return _input_error(args.path, e, "record the checker reply for")
    try:
        rec = checker.record(args.path, ledger, text, check_path, display, root)
    except (checker.StaleLedger, checker.StaleReply) as e:  # nothing written; any earlier record is left as it is
        print(f"plainspoken: checker reply not recorded: {e}", file=sys.stderr)
        return 1
    except checker.ReplyError as e:  # recorded as INCOMPLETE, so no earlier PASS outlives it
        print(f"plainspoken: checker reply rejected ({check_path} now says INCOMPLETE): {_first_line(e)}",
              file=sys.stderr)
        return 2
    except claims.LedgerError as e:
        return _input_error(ledger, e, "read the ledger")
    except _INPUT_ERRORS as e:
        return _input_error(args.path, e, "record the checker reply for")
    print(f"claims-check: {rec['result']} · {len(rec['findings'])} finding(s): {rec['blocking']} blocking, "
          f"{rec['warnings']} warning(s) · {rec['unverified_evidence']} with unverified evidence"
          + (" · prose outside the JSON ignored" if rec["reply_had_prose"] else ""))
    for f in rec["findings"]:
        mark = "" if f["evidence_verified"] else " [evidence unverified: not verbatim in the article or a pinned passage]"
        print(f"  {f['severity']} {f.get('claim_id') or '-'} {f.get('class') or '-'}: {str(f.get('evidence'))[:120]}"
              f"{mark}")
    print(f"wrote {check_path}")
    return 0 if rec["result"] == "PASS" else 1


def _pin(args: argparse.Namespace, root: Path) -> int:
    if not args.additional and (args.source_url is not None or args.locator is not None):
        return _usage("--source-url and --locator go with --additional")
    if args.additional and args.snapshot_path is not None:
        return _usage("--snapshot-path doesn't go with --additional: an additional passage is rechecked against "
                      "the primary binding's source_snapshot")
    if args.source_url is not None and not args.source_url.startswith("https://"):
        return _usage(f"--source-url must start with https:// (got {args.source_url!r})")
    try:
        text = args.source.read_text(encoding="utf-8")
    except _INPUT_ERRORS as e:
        return _input_error(args.source, e, "read the source")
    try:
        sources_dir = config.claims_settings(root)["sources_dir"]
    except _INPUT_ERRORS as e:  # ConfigError: a malformed [claims] section
        return _input_error(args.source, e, "pin from")
    articles: tuple[Path, ...] = ()
    if args.article is not None:
        try:  # strict, so a symlink loop fails the same way on every Python
            articles = (args.article.resolve(strict=True),)
        except (OSError, ValueError, RuntimeError) as e:  # missing, a loop (RuntimeError before 3.13), a NUL
            return _input_error(args.article, e, "use the article")
        if not articles[0].is_file():
            return _usage(f"can't use the article {args.article}: not a file")
    try:  # the source must be saved under sources_dir and never be the article
        source_rel = claims_tools.project_relative(args.source, root)
    except ValueError:
        return _usage(f"pin refused: --source {args.source} is outside the project: save the source's text under "
                      f"{sources_dir.rstrip('/')}/ and pin from that")
    candidates = [("--source", os.path.relpath(os.path.abspath(args.source), root))]  # links not followed yet
    if args.snapshot_path is not None and pinning.safe_relative(args.snapshot_path):  # else binding_fields refuses
        candidates.append(("--snapshot-path", args.snapshot_path))
    for flag, rel in candidates:
        try:
            problem = pinning.source_problem(root, Path(rel), sources_dir, articles)
        except (OSError, ValueError, RuntimeError) as e:
            return _input_error(Path(rel), e, "resolve")
        if problem is not None:
            return _usage(f"pin refused: {flag} {problem}")
    if args.snapshot_path is not None and pinning.safe_relative(args.snapshot_path):  # check it now
        problem = pinning.snapshot_problem(root, args.snapshot_path, text)
        if problem is not None:
            return _usage(f"pin refused: --snapshot-path {problem}")
    snapshot = args.snapshot_path
    if snapshot is None and not args.additional:
        snapshot = source_rel
    try:
        print(claims_tools.pin_fragment(text, args.passage, retrieved_at=args.retrieved_at or _util.now_iso(),
                                        source_snapshot=snapshot, additional=args.additional,
                                        source_url=args.source_url, locator=args.locator), end="")
    except ValueError as e:
        return _usage(f"pin refused: {_first_line(e)}")
    return 0


def _stamp(args: argparse.Namespace, root: Path) -> int:
    try:
        args.path.read_bytes()  # an unreadable article is named before any ledger lookup
        ledger = args.ledger or claims.ledger_path_for(args.path, root)
        text, values = claims_tools.stamp(args.path, ledger, root, extraction.platform_names(root), args.by)
    except claims_tools.NotReady as e:
        print(f"plainspoken: not stamped: {e}", file=sys.stderr)
        return 1
    except _INPUT_ERRORS as e:
        return _input_error(args.path, e, "stamp the ledger for")
    try:
        report.write_atomic(ledger, text)
    except OSError as e:
        return _input_error(ledger, e, "write")
    print(f"stamped {ledger}: " + ", ".join(f"{k} = {v}" for k, v in values.items()))
    return 0


def _scaffold(args: argparse.Namespace, root: Path) -> int:
    try:
        out = args.out or claims.ledger_path_for(args.path, root)
    except _INPUT_ERRORS as e:
        return _input_error(args.path, e, "find the ledger for")
    if out.exists():  # before the suffix check: the default path is the .claims.json one when only that exists
        print(f"plainspoken: a ledger already exists: {out} (scaffold never overwrites a ledger)", file=sys.stderr)
        return 2
    if args.out is not None and out.suffix.lower() != ".toml":
        return _usage(f"--out {out}: scaffold writes TOML, so name a .toml file")
    try:
        ledger = claims_tools.scaffold(args.path, root, id_prefix=args.id_prefix,
                                       platforms=extraction.platform_names(root))
    except _INPUT_ERRORS as e:
        return _input_error(args.path, e, "scaffold a ledger for")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as f:  # "x": never overwrite, even in a race
            f.write(claims_tools.scaffold_text(ledger))
    except OSError as e:
        return _input_error(out, e, "write")
    print(f"wrote {out}: {len(ledger['claims'])} candidate claim(s), each blocking until reviewed")
    return 0


def _justify(path: Path, want_template: bool, reports: Path | None, calibration_notes: str | None, write: bool,
             root: Path) -> int:
    d = reports or report.reports_dir_default(root)
    try:
        sha = report.sha256(path)
    except _INPUT_ERRORS as e:
        return _input_error(path, e)
    rep = justify.read_json(report.report_paths(path, d, root)["report"])
    if rep is None or rep.get("article_sha256") != sha:
        print(f"plainspoken: no current report for {path.name} — run `merge` first", file=sys.stderr)
        return 2
    jpath = report.report_paths(path, d, root)["justify"]
    if want_template:
        if (rep.get("coverage") or {}).get("missing"):
            print("plainspoken: report is INCOMPLETE — fix its inputs and merge first", file=sys.stderr)
            return 2
        text = json.dumps(justify.template(rep, justify.read_json(jpath)), indent=2, ensure_ascii=False)
        if not write:
            print(text)
            return 0
        try:
            report.write_atomic(jpath, text + "\n")
        except OSError as e:
            return _input_error(path, e, "write the justifications for")
        print(jpath)
        return 0
    data = justify.read_json(jpath)
    if data is None:
        print(f"plainspoken: {jpath.name} missing or not a JSON object (start from `justify --template`)", file=sys.stderr)
        return 1
    errors = justify.validate_justify(data)
    if data.get("article_sha256") != sha:
        errors.append("justify: written for an older version of the article")
    if errors:
        print("invalid justifications:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    payload = justify.review_input(rep, data, justify.file_sha(jpath))
    payload["article"] = str(Path(path).resolve())
    payload["rubric"] = str(judges.RUBRIC)
    payload["calibration_notes"] = calibration_notes
    if not payload["items"]:
        print(f"plainspoken: nothing to review: no justification in {jpath.name} covers a failing WARN rule",
              file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _kaizen_parser(sub) -> None:
    kz = sub.add_parser("kaizen", help="the kaizen loop: ledger overrides, metrics, and approval-gated ruleset "
                                       "proposals")
    ks = kz.add_subparsers(dest="kaizen_cmd", required=True)

    def article(p, profile=False):
        p.add_argument("path", type=Path)
        p.add_argument("--reports", type=Path)
        if profile:
            p.add_argument("--profile", help="the profile the check used (default: found from the saved lint)")
        return p

    d = article(ks.add_parser("dismiss", help="record that a rule's finding in the current check is wrong"), True)
    d.add_argument("--rule", required=True)
    d.add_argument("--kind", required=True, choices=overrides.OVERRIDE_KINDS)
    d.add_argument("--reason", required=True, help="why, in a few words (at most 200 characters are kept)")
    d.add_argument("--line", type=int, help="only the finding on this line")
    d.add_argument("--from-snapshot", action="store_true",
                   help="use the last check's findings, saved with its snapshot, when the file changed since (a "
                        "finding the fix pass removed)")
    u = article(ks.add_parser("uphold", help="record that a rule's finding in the current check is right"), True)
    u.add_argument("--rule", required=True)
    u.add_argument("--reason", required=True, help="why, in a few words (at most 200 characters are kept)")
    u.add_argument("--line", type=int, help="only the finding on this line")
    df = article(ks.add_parser("diff", help="the numbered sentence-level hunks since the last check"))
    df.add_argument("--json", action="store_true")
    mi = article(ks.add_parser("missed", help="record a tell the check missed in one diff hunk"))
    mi.add_argument("--hunk", type=int, required=True)
    which = mi.add_mutually_exclusive_group(required=True)
    which.add_argument("--rule", help="the ruleset rule that should have caught it")
    which.add_argument("--pattern", help="a name for a tell no rule covers ([a-z0-9-]{1,40})")
    mi.add_argument("--reason", help="why, in a few words (at most 200 characters are kept)")
    article(ks.add_parser("published", help="record the check's findings that are still in the published file"), True)
    rp = ks.add_parser("report", help="per-rule kaizen metrics from the ledger (no composite score)")
    rp.add_argument("--since", help="only events at or after this ISO date or datetime (a date is 00:00 UTC)")
    rp.add_argument("--until", help="only events before this ISO date or datetime (a date is 00:00 UTC)")
    rp.add_argument("--json", action="store_true", help="the metrics as JSON")
    rp.add_argument("--share", action="store_true", help="anonymised counts (JSON) to paste into an upstream issue")
    ca = ks.add_parser("calibrate", help="propose at most 3 ruleset changes from the ledger and send them through "
                                         "the adapter, re-sending any that weren't sent (never applies them)")
    ca.add_argument("--now", help="calibrate as of this ISO date or datetime (default: now)")
    ca.add_argument("--corpus", nargs="+", metavar="GLOB",
                    help="files to measure each proposal's effect on (default: [kaizen] corpus)")
    ca.add_argument("--json", action="store_true", help="the new proposals as JSON")
    mn = ks.add_parser("mine", help="compare model drafts written from the fixed briefs with a human corpus and "
                                    "queue at most 5 model-tagged proposals locally (never sends or applies them)")
    mn.add_argument("--drafts", type=Path, required=True, metavar="DIR",
                    help="the drafts, as DIR/<model id>/*.md (relative to the project root)")
    mn.add_argument("--corpus", nargs="+", metavar="GLOB",
                    help="human-written files, relative to the project root (default: [kaizen] human_corpus)")
    mn.add_argument("--briefs", type=Path, metavar="DIR", help="the briefs the drafts were written from, relative "
                                                                "to the project root (default: the plugin's "
                                                                "evals/briefs/); a folder holding .heldout "
                                                                "is refused")
    mn.add_argument("--json", action="store_true", help="the full result as JSON")
    mn.add_argument("--dry-run", action="store_true", help="show the candidates; store and log nothing")
    ks.add_parser("decisions", help="record the APPROVE:/REJECT: decisions people made through the adapter "
                                    "(never sends anything)")
    rv = ks.add_parser("review", help="the proposals waiting for a decision or for `kaizen apply`")
    rv.add_argument("--json", action="store_true")
    ap_ = ks.add_parser("apply", help="apply an approved proposal to a ruleset checkout or the profile it was made for")
    ap_.add_argument("id")
    ap_.add_argument("--rules", type=Path, help="the rules.toml to edit (default: the plugin's own, if it's a "
                                                "git checkout)")
    ap_.add_argument("--target", choices=proposals.TARGETS, default="ruleset")
    ap_.add_argument("--dry-run", action="store_true", help="print the diff and write nothing")


def _kaizen_line(e: dict) -> str:
    facets = ", ".join(f"{k} {v}" for k, v in sorted(e["facets"].items()))
    return (f"  {e['outcome']} · rule {e['rule']} · {e['severity'] or '-'} · span {e['span_hash']}"
            + (f" · {facets}" if facets else ""))


def _hunk_lines(h: dict) -> list[str]:
    a, b = h["old_lines"]
    where = f"L{a}" if a == b else f"L{a}-{b}"
    return [f"[{h['n']}] {where}", f"  - {h['old'] or '(nothing)'}", f"  + {h['new'] or '(deleted)'}"]


def _kaizen_report(args: argparse.Namespace, root: Path) -> int:
    """`kaizen report`: always exit 0 once the window and settings are good, even on an empty or damaged ledger."""
    window = {}
    for flag in ("since", "until"):
        value = getattr(args, flag)
        try:
            window[flag] = None if value is None else kaizen.parse_when(value)
        except ValueError as e:
            print(f"plainspoken: kaizen report: --{flag}: {_first_line(e)}", file=sys.stderr)
            return 2
    try:  # a bad [kaizen] section or a ruleset that won't load is one line and exit 2
        settings = config.kaizen_settings(root, os.environ)
        cfg = load_config()
    except (ValueError, OSError) as e:  # ConfigError, ProfileError and TOMLDecodeError are ValueErrors
        print(f"plainspoken: kaizen report: {_first_line(e)}", file=sys.stderr)
        return 2
    events, bad = ledger.read(settings, window["since"], window["until"])
    rows, bad_friction = ledger.read_friction(settings, window["since"], window["until"])
    metrics = kaizen.rule_metrics(events, cfg, datetime.now(timezone.utc))
    if args.share:
        out = kaizen.share(metrics, cfg, kaizen.plugin_version(), **window)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    patterns = kaizen.pattern_metrics(events)
    friction = kaizen.friction_summary(rows, ledger.distinct(events))
    if args.json:
        print(json.dumps({"window": window, "rules": metrics, "patterns": patterns, "bad_lines": bad + bad_friction,
                          "friction": friction}, indent=2, ensure_ascii=False))
        return 0
    print("\n".join(kaizen.report_lines(metrics, bad + bad_friction, friction, patterns)))
    return 0


def _kaizen_settings(cmd: str, root: Path) -> dict | None:
    try:  # a bad [kaizen] section, kaizen.toml or ruleset is one line and exit 2
        return {**config.kaizen_settings(root, os.environ), **calibrate.load_settings()}
    except (ValueError, OSError) as e:
        print(f"plainspoken: kaizen {cmd}: {_first_line(e)}", file=sys.stderr)
        return None


def _kaizen_calibrate(args: argparse.Namespace, root: Path) -> int:
    try:
        now = datetime.fromisoformat(kaizen.parse_when(args.now)) if args.now else datetime.now(timezone.utc)
    except ValueError as e:
        print(f"plainspoken: kaizen calibrate: --now: {_first_line(e)}", file=sys.stderr)
        return 2
    settings = _kaizen_settings("calibrate", root)
    if settings is None:
        return 2
    resent: list[dict] = []
    try:
        made = calibrate.run(root, settings, now, args.corpus, resent=resent)
    except (ValueError, OSError) as e:
        print(f"plainspoken: kaizen calibrate: {_first_line(e)}", file=sys.stderr)
        return 2
    # The Stop nudge's clock, proposals or not. Real time, never --now: a future --now would silence the nudge.
    kaizen.mark_calibrated(settings, datetime.now(timezone.utc))
    for p in resent + made:
        _emit_note(p)
    if args.json:
        print(json.dumps(made, indent=2, ensure_ascii=False))
        return 0
    for p in resent:
        print(f"{p['id']}: sent again: " + (f"emitted to {adapters.describe(p.get('adapter'), p['ref'])}"
                                            if p.get("ref") else f"not emitted: {p.get('emit_error', 'unknown')}"))
    if not made:
        print("kaizen calibrate: no proposals" + (" (no new ones)" if resent else ""))
        return 0
    unsent = 0
    for p in made:
        print(f"{p['id']}: {p['summary']}")
        if p["diff"]:
            print(p["diff"].rstrip("\n"))
        if p.get("ref"):
            print(f"  emitted to {adapters.describe(p.get('adapter'), p['ref'])}")
        else:
            unsent += 1
            print(f"  not emitted: {p.get('emit_error', 'unknown error')}")
        print()
    print(f"kaizen calibrate: {len(made)} proposal{'s' if len(made) != 1 else ''} stored; nothing was applied"
          + (f"; {unsent} not emitted (fix the adapter, then run `kaizen calibrate` again to send "
             f"{'them' if unsent != 1 else 'it'})" if unsent else ""))
    return 0


def _emit_note(p: dict) -> None:
    """One stderr line for a proposal that wasn't sent, or was sent but whose file couldn't record the ref."""
    if p.get("save_error"):
        print(f"plainspoken: kaizen calibrate: {p['id']} {p['save_error']}: note the ref, or the next calibrate "
              "sends it again", file=sys.stderr)
    elif not p.get("ref"):
        print(f"plainspoken: kaizen calibrate: {p['id']} not emitted: {p.get('emit_error', 'unknown error')}",
              file=sys.stderr)


def _kaizen_review(args: argparse.Namespace, root: Path) -> int:
    settings = _kaizen_settings("review", root)
    if settings is None:
        return 2
    events = ledger.read(settings)[0]
    # A superseded proposal is listed for one calibrate cycle after apply refused it, so the person sees why it went.
    recent = datetime.now(timezone.utc) - timedelta(days=settings["triggers"]["cycle_days"])
    rows = []
    for p in proposals.stored(settings):
        state = proposals.status(p["id"], events)
        if state == proposals.SUPERSEDED:
            try:
                if datetime.fromisoformat(proposals.superseded(p["id"], events)["ts"]) < recent:
                    continue
            except (TypeError, ValueError, KeyError):
                continue
        if state in ("pending", "approved", proposals.SUPERSEDED):
            d = proposals.decision(p["id"], events)
            by = (d or {}).get("facets", {}).get("by", "unknown")
            note = {"pending": "awaiting decision", "approved": f"approved by {by}, not applied",
                    proposals.SUPERSEDED: f"superseded (approved by {by}, then stale at apply; closed, nothing "
                                          "to do)"}[state]
            rows.append({**p, "status": note, "state": state})
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not any(p["state"] != proposals.SUPERSEDED for p in rows):
        print("kaizen review: no proposals waiting")
    for p in rows:
        print(f"{p['id']} · rule {p['rule']} · {p['trigger']} · {p['action']} · {p['status']}")
        print(f"  {p['summary']}")
    return 0


def _kaizen_apply(args: argparse.Namespace, root: Path) -> int:
    settings = _kaizen_settings("apply", root)
    if settings is None:
        return 2
    try:
        out = proposals.apply(args.id, root, settings, args.rules, args.target, args.dry_run)
    except proposals.UnknownProposal as e:
        print(f"plainspoken: kaizen apply: {_first_line(e)}", file=sys.stderr)
        return 2
    except proposals.Refused as e:
        print(f"plainspoken: kaizen apply: refused: {_first_line(e)}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(f"plainspoken: kaizen apply: refused: {_first_line(e)}", file=sys.stderr)
        return 1
    print(out["diff"].rstrip("\n"))
    for note in out.get("rubric_notes") or ():
        print(f"kaizen apply: {note}")
    if out.get("rebased"):
        print(f"kaizen apply: {out['id']}: rebased onto the current ruleset (it changed since calibrate; "
              "every edit still applies)")
    if out["dry_run"]:
        print(f"kaizen apply: dry run, nothing written ({out['path']})")
        return 0
    if not out["logged"]:
        print("plainspoken: kaizen apply: the apply event couldn't be written to the ledger", file=sys.stderr)
    if out["changelog_error"]:
        print(f"plainspoken: kaizen apply: {out['id']} applied to {out['path']}; changelog not written: "
              f"{out['changelog_error']}", file=sys.stderr)
        return 1
    print(f"kaizen apply: {out['id']} applied to {out['path']} (ruleset {out['version']}); changelog "
          f"{out['changelog']}")
    return 0


def _kaizen_decisions(args: argparse.Namespace, root: Path) -> int:
    """`kaizen decisions`: 0 when every adapter answered (with or without new decisions), 1 when any failed."""
    settings = _kaizen_settings("decisions", root)
    if settings is None:
        return 2
    lines, errors = adapters.record_decisions(settings, datetime.now(timezone.utc))
    for line in lines:
        print(line)
    for line in errors:
        print(f"plainspoken: kaizen decisions: {line}", file=sys.stderr)
    if not lines and not errors:
        print("kaizen decisions: no new decisions")
    return 1 if errors else 0


def _mine_label(c: dict) -> str:
    ev = c.get("evidence") or {}
    what = f'phrase "{ev["phrase"]}"' if "phrase" in ev else f"rule {c['rule']}"
    return (f"{c['id']}: {c.get('model')} · {what} · ratio {ev.get('ratio')} · share {ev.get('share', 0):.2f} · "
            f"{c['action']}")


def _kaizen_mine(args: argparse.Namespace, root: Path) -> int:
    """`kaizen mine`: 0 with or without candidates, 2 for bad input (no drafts, no corpus, a bad model folder)."""
    settings = _kaizen_settings("mine", root)
    if settings is None:
        return 2
    try:
        cfg = load_config()
        settings["mining"] = mining.load_settings(cfg=cfg)
        prof = config.resolve_profile(None, root, os.environ, plugin_option=config.PLUGIN_DEFAULT)
        briefs = None if args.briefs is None else args.briefs if args.briefs.is_absolute() else root / args.briefs
        mining.refuse_heldout(mining.BRIEFS if briefs is None else briefs)  # held-out data: refused first
        globs = args.corpus or settings["human_corpus"]
        try:
            files = calibrate.corpus_files(root, globs)
        except (NotImplementedError, ValueError) as e:
            raise mining.MiningError(f"--corpus: globs are relative to the project root ({_first_line(e)})") from None
        if not files:
            raise mining.MiningError("no human corpus: " + (f"{' '.join(globs)} matched no files under {root}" if globs
                                                            else "pass --corpus GLOB or set [kaizen] human_corpus"))
        drafts = args.drafts if args.drafts.is_absolute() else root / args.drafts  # like --corpus: from the root
        out = mining.mine(drafts, files, briefs, cfg, prof, settings, dry_run=args.dry_run)
    except (ValueError, OSError) as e:  # MiningError, ConfigError and ProfileError are ValueErrors
        print(f"plainspoken: kaizen mine: {_first_line(e)}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    for model, m in out["models"].items():
        print(f"{model}: {m['drafts']} draft{'s' if m['drafts'] != 1 else ''}, {m['words']} words"
              + (f" (skipped: {m['skipped']})" if m.get("skipped") else ""))
    print(f"human corpus: {out['corpus']['files']} file{'s' if out['corpus']['files'] != 1 else ''}, "
          f"{out['corpus']['words']} words")
    if not out["candidates"]:
        print("kaizen mine: no candidates")
        return 0
    for c in out["candidates"]:
        print(_mine_label(c))
        if c.get("save_error"):
            print(f"plainspoken: kaizen mine: {c['id']} {c['save_error']}: the next kaizen mine writes it again",
                  file=sys.stderr)
    n = len(out["candidates"])
    print(f"kaizen mine: {n} candidate{'s' if n != 1 else ''} "
          + ("(dry run: nothing stored)" if out["dry_run"] else
             "stored in the local queue (not sent; see `kaizen review`); nothing was applied"))
    return 0


def _kaizen(args: argparse.Namespace, root: Path) -> int:
    cmd = args.kaizen_cmd
    if cmd == "report":
        return _kaizen_report(args, root)
    if cmd in ("calibrate", "review", "apply", "decisions", "mine"):
        return {"calibrate": _kaizen_calibrate, "review": _kaizen_review, "apply": _kaizen_apply,
                "decisions": _kaizen_decisions, "mine": _kaizen_mine}[cmd](args, root)
    try:
        if cmd == "diff":
            found = overrides.hunks(args.path, root, reports_dir=args.reports)
            if args.json:
                print(json.dumps(found, indent=2, ensure_ascii=False))
            else:
                print("\n".join(x for h in found for x in _hunk_lines(h)) or "(no changes since the last check)")
            return 0
        if cmd in ("dismiss", "uphold"):
            recorded = overrides.override(args.path, root, args.rule, "dismissed" if cmd == "dismiss" else "upheld",
                                          getattr(args, "kind", None), args.reason, args.line,
                                          reports_dir=args.reports, profile=args.profile,
                                          from_snapshot=getattr(args, "from_snapshot", False))
        elif cmd == "missed":
            recorded = [overrides.missed(args.path, root, args.hunk, args.rule, args.pattern, args.reason,
                                         reports_dir=args.reports)]
        else:
            recorded = overrides.published(args.path, root, reports_dir=args.reports, profile=args.profile)
    except (overrides.UsageError, config.ConfigError, ProfileError, UnicodeDecodeError) as e:
        print(f"plainspoken: kaizen {cmd}: {_first_line(e)}", file=sys.stderr)
        return 2
    except ledger.LedgerError as e:
        print(f"plainspoken: kaizen {cmd}: nothing recorded: {_first_line(e)}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"plainspoken: kaizen {cmd}: {_first_line(e)}", file=sys.stderr)
        return 1
    except OSError as e:
        return _input_error(args.path, e, f"kaizen {cmd}")
    if not recorded:
        print(f"kaizen {cmd}: nothing to record (no finding from the check is still in {args.path.name})")
        return 0
    print(f"kaizen {cmd}: recorded {len(recorded)} event{'s' if len(recorded) != 1 else ''} for {args.path.name}")
    for e in recorded:
        print(_kaizen_line(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
