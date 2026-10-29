"""The kaizen proposal store, decisions and `kaizen apply` (Phase 5).

A proposal is a JSON file, `<proposals_dir>/proposals/<id>.json`, written by `calibrate` (or `mine`). Its decision
lives in the ledger: a `decision` event (outcome `approved` or `rejected`, facet `by`) with `proposal` set to the id,
recorded from the adapter by `kaizen decisions`. The latest decision wins. Nothing in the plugin writes one itself.

`apply` is the only code that edits a ruleset or a profile, and it fails closed: no approval, a rejection, a
`review` proposal, an installed plugin's own ruleset, a target the proposal doesn't allow, a profile target whose
profile (the one the proposal was made for) isn't a project file, or an edit that no longer applies all raise
`Refused` and write nothing to the target. Staleness is per edit: when the
target changed since calibrate (the base hash differs), the stored edits are re-applied to the current text, and only
an edit whose `old` value (or list, or rule) moved refuses (`Stale`); otherwise the proposal applies, "rebased onto
the current ruleset".

A proposal whose rule had another proposal applied after it was made is stale too: that apply spent the evidence
it rests on (a profile apply only for that profile).

A stale refusal (not a dry run) records the proposal as `superseded`: one ledger event (`apply`, actor `engine`,
outcome `superseded`). A superseded proposal is closed, like an applied one: its key is free, so calibrate may
propose for the rule again once the evidence builds, and no later decision reopens it. Nothing is written to the
proposal file, so a store written before the state existed reads as it did.

An apply to a checkout (`--rules`) isn't in use until that checkout's change is released and installed: until the
ruleset in use reaches the version the apply wrote (the `applied` event's `ruleset_version`), or its changelog has the
proposal's entry, the proposal is `awaiting_release` (`released`). Nothing new is written for this: every `applied`
event has always recorded the version it wrote, so older ledgers read the same way.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import config, ledger, registry, report, rulesedit
from plainspoken import profile as _profile

ID = re.compile(r"KZ-\d{8}-[0-9a-f]{6}")
TARGETS = ("ruleset", "profile")
CHANGELOG = "RULESET-CHANGELOG.md"
CHANGELOG_TITLE = "# Ruleset changelog"
PROFILE_CHANGELOG_TITLE = "# Kaizen profile changelog"


def _first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


class Refused(ValueError):
    """`kaizen apply` won't write: the message says why and what to do instead. Nothing was written."""


class Stale(Refused):
    """`kaizen apply` refused because an edit no longer applies to the target. Nothing was written to the
    target; outside a dry run the proposal is now `superseded`."""


class UnknownProposal(ValueError):
    """No stored proposal has that id (or the id isn't one)."""


def digest(obj) -> str:
    """sha256 hex of the canonical JSON of `obj`."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def proposal_id(now: datetime, p: Mapping) -> str:
    """`KZ-<YYYYMMDD of now>-<6 hex>` over everything `apply` acts on: the edits, rule, action, version bump and
    allowed targets; over rule + trigger + action when there are no edits (a review proposal)."""
    edits = list(p.get("edits") or [])
    basis = ({"edits": edits, **{k: p.get(k) for k in ("rule", "action", "bump", "targets")}} if edits
             else {k: p.get(k) for k in ("rule", "trigger", "action")})
    return f"KZ-{now.astimezone(timezone.utc):%Y%m%d}-{digest(basis)[:6]}"


def _intact(p: Mapping) -> bool:
    """The stored id still matches what apply acts on (edits, rule, action, bump, targets) and the date it was
    made, so a hand edit to any of them after approval refuses."""
    try:
        return proposal_id(datetime.fromisoformat(str(p.get("created"))), p) == p["id"]
    except (TypeError, ValueError, KeyError):
        return False


def _folder(settings: Mapping) -> Path:
    return Path(settings["proposals_dir"]) / "proposals"


def _linked(settings: Mapping) -> Path | None:
    """The first symlink among the proposals folder and the folders between the project root and it: the store
    is written and read only through real folders, as the ledger is."""
    root = settings.get("root")
    return ledger.symlinked(_folder(settings), Path(root) if root is not None else None)


def _path(pid: str, settings: Mapping) -> Path:
    if not (isinstance(pid, str) and ID.fullmatch(pid)):
        raise UnknownProposal(f"{pid!r} isn't a proposal id (KZ-YYYYMMDD-xxxxxx)")
    return _folder(settings) / f"{pid}.json"


def save(p: dict, settings: Mapping) -> Path:
    """Write the proposal atomically; its path. A symlinked proposals folder (or one between the root and it) is an
    OSError and nothing is written."""
    path = _path(p.get("id"), settings)
    link = _linked(settings)
    if link is not None:
        raise OSError(f"{link}: the proposals folder is a symlink, so nothing was written")
    report.write_atomic(path, json.dumps(p, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load(pid: str, settings: Mapping) -> dict:
    path = _path(pid, settings)
    link = _linked(settings)
    if link is not None:
        raise UnknownProposal(f"{link}: the proposals folder is a symlink, so nothing is read from it")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UnknownProposal(f"no proposal {pid} in {_folder(settings)}") from None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise UnknownProposal(f"{path}: can't read the proposal ({e})") from None
    if not isinstance(data, dict) or data.get("id") != pid:
        raise UnknownProposal(f"{path}: not a proposal for {pid}")
    return data


def stored(settings: Mapping) -> list[dict]:
    """Every readable stored proposal, by id."""
    folder = _folder(settings)
    if _linked(settings) is not None or not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("KZ-*.json")):
        try:
            out.append(load(path.stem, settings))
        except UnknownProposal:
            continue
    return out


def decision(pid: str, events: Iterable[dict]) -> dict | None:
    """The latest `decision` event (approved or rejected) for proposal `pid`; on a tied `ts`, the later line."""
    best = None
    for e in events:
        if e.get("event") == "decision" and e.get("proposal") == pid and e.get("outcome") in ("approved", "rejected"):
            if best is None or str(e.get("ts", "")) >= str(best.get("ts", "")):
                best = e
    return best


def applied(pid: str, events: Iterable[dict]) -> bool:
    return any(e.get("event") == "apply" and e.get("outcome") == "applied" and e.get("proposal") == pid
               for e in events)


SUPERSEDED = "superseded"


def superseded(pid: str, events: Iterable[dict]) -> dict | None:
    """The latest `superseded` event for proposal `pid` (apply refused it as stale), or None."""
    best = None
    for e in events:
        if e.get("event") == "apply" and e.get("outcome") == SUPERSEDED and e.get("proposal") == pid:
            if best is None or str(e.get("ts", "")) >= str(best.get("ts", "")):
                best = e
    return best


AWAITING = "awaiting_release"


def _semver(v: object) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v) if isinstance(v, str) else None
    return None if m is None else (int(m[1]), int(m[2]), int(m[3]))


def in_use(path: Path | None = None) -> tuple[str | None, str]:
    """The ruleset in use (`PLAINSPOKEN_RULES`, else the plugin's own): its version (None when it can't be read) and
    the text of the `RULESET-CHANGELOG.md` beside it ("" when there's none)."""
    path = Path(path) if path is not None else default_rules()
    try:
        version = tomllib.loads(path.read_text(encoding="utf-8")).get("version")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        version = None
    try:
        log = (path.parent / CHANGELOG).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        log = ""
    return (version if isinstance(version, str) else None), log


def released(e: Mapping, use: tuple[str | None, str] | None = None) -> bool:
    """An `applied` event's change has reached the ruleset in use (`use`, from `in_use`). A ruleset apply records the
    version it wrote as the event's `ruleset_version` (it always has), so the change is released once the ruleset in
    use is at that version or later, or once the changelog beside it has the proposal's entry. A profile apply edits
    a project file, so it's in use at once. An event whose version, or a ruleset whose version, isn't
    MAJOR.MINOR.PATCH counts as released, as every apply did before this state existed."""
    if (e.get("facets") or {}).get("kind") == "profile":
        return True
    version, log = in_use() if use is None else use
    want, have = _semver(e.get("ruleset_version")), _semver(version)
    if want is None or have is None or have >= want:
        return True
    pid = e.get("proposal")
    return isinstance(pid, str) and re.search(rf"(?m)^- {re.escape(pid)}:", log) is not None


def awaiting_release(events: Iterable[dict], use: tuple[str | None, str] | None = None) -> list[dict]:
    """The `applied` events whose change hasn't reached the ruleset in use: applied to a checkout (`--rules`) that
    hasn't been released and installed yet."""
    use = in_use() if use is None else use
    return [e for e in events if e.get("event") == "apply" and e.get("outcome") == "applied" and not released(e, use)]


def status(pid: str, events: list[dict], use: tuple[str | None, str] | None = None) -> str:
    """`applied` (and in the ruleset in use), `awaiting_release` (applied to a checkout whose change hasn't reached
    the ruleset in use yet), `superseded` (approved, then refused as stale; closed), `approved` (not applied yet),
    `rejected` or `pending` (no decision). `use` is `in_use()`, read when needed."""
    done = [e for e in events if e.get("event") == "apply" and e.get("outcome") == "applied"
            and e.get("proposal") == pid]
    if done:
        use = in_use() if use is None else use
        return "applied" if any(released(e, use) for e in done) else AWAITING
    if superseded(pid, events) is not None:
        return SUPERSEDED
    d = decision(pid, events)
    return "pending" if d is None else d["outcome"]


def pending(settings: Mapping, events: list[dict] | None = None) -> list[dict]:
    """Stored proposals with no decision yet."""
    events = ledger.read(settings)[0] if events is None else events
    return [p for p in stored(settings) if decision(p["id"], events) is None]


# --- apply ---------------------------------------------------------------------------------------------------------

def default_rules() -> Path:
    return Path(os.environ.get("PLAINSPOKEN_RULES") or registry.DEFAULT_PATH)


def _installed(path: Path) -> bool:
    """`path` is the plugin's own ruleset and the plugin root isn't a git checkout (an installed plugin's cache)."""
    try:
        own = config.resolve_path(path) == config.resolve_path(registry.DEFAULT_PATH)
    except (OSError, RuntimeError):
        own = True
    return own and not (registry.DEFAULT_PATH.parents[1] / ".git").exists()


def _prepend(path: Path, entry: str, title: str) -> str:
    """The changelog text with `entry` as its newest section: before the first `## ` heading, keeping the title and
    intro; a new file starts with `title`."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"{title}\n\n{entry}"
    lines = text.splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if line.startswith("## ")), None)
    if at is None:
        body = text if text.endswith("\n") else text + "\n"
        return body + ("" if body.endswith("\n\n") else "\n") + entry
    return "".join(lines[:at]) + entry + "\n" + "".join(lines[at:])


def _approver(d: Mapping) -> str:
    by = (d.get("facets") or {}).get("by")
    return by if isinstance(by, str) and by.strip() else "unknown"


def _log_apply(p: dict, version: str, approver: str, settings: Mapping, now: datetime, target: str) -> bool:
    """The `applied` event: facet `by` (the approver) and `kind` (the target, `ruleset` or `profile`: a profile
    apply spends only that profile's evidence)."""
    try:
        ledger.append(ledger.make_event(event="apply", actor="engine", outcome="applied", ruleset_version=version,
                                        profile=str(p.get("profile") or "unknown"), rule=p.get("rule"),
                                        proposal=p["id"], facets={"by": approver[:ledger.MAX_FACET], "kind": target},
                                        ts=now), settings)
    except ledger.LedgerError:
        return False
    return True


STALE = "stale proposal"


def _spent_by(p: Mapping, events: Iterable[dict], target: str) -> dict | None:
    """Another proposal for `p`'s rule applied after `p` was made, whose apply spent the evidence `p` rests on:
    a ruleset apply (or one logged before the target was recorded) spends every profile's; a profile
    apply spends its own profile's, so it counts only for a profile target on the same profile."""
    try:
        made = datetime.fromisoformat(str(p.get("created")))
    except ValueError:
        return None
    for e in events:
        if not (e.get("event") == "apply" and e.get("outcome") == "applied" and e.get("rule") == p.get("rule")
                and e.get("proposal") != p.get("id")):
            continue
        kind = (e.get("facets") or {}).get("kind")
        if kind == "profile" and not (target == "profile" and e.get("profile") == p.get("profile")):
            continue
        try:
            if datetime.fromisoformat(e["ts"]) > made:
                return e
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _stale(e: BaseException) -> Stale:
    return Stale(f"{STALE} ({_first_line(e)})")


def _supersede(p: dict, error: Stale, version: str, approver: str, settings: Mapping, now: datetime,
               dry_run: bool) -> Stale:
    """The refusal for a stale proposal. Outside a dry run it's recorded as `superseded` first, which closes it and
    frees its rule for calibrate; a dry run writes nothing and says what a real apply would do."""
    if dry_run:
        return Stale(f"{error}: `kaizen apply {p['id']}` without --dry-run marks it superseded (nothing else is "
                     "written), and calibrate can propose for the rule again")
    try:
        ledger.append(ledger.make_event(event="apply", actor="engine", outcome=SUPERSEDED, ruleset_version=version,
                                        profile=str(p.get("profile") or "unknown"), rule=p.get("rule"),
                                        proposal=p["id"], facets={"by": approver[:ledger.MAX_FACET]}, ts=now),
                      settings)
    except ledger.LedgerError as e:
        return Stale(f"{error}; it couldn't be marked superseded ({_first_line(e)}): run apply again once the "
                     "ledger can be written")
    return Stale(f"{error}: marked superseded, nothing else written; calibrate can propose for the rule again "
                 "when new evidence builds")


def _rebase_check(text: str, edits: list[dict]) -> str:
    """The ruleset changed since calibrate: the stored edits must still apply to the current text, each
    on its own terms. A threshold or rule field must still hold the `old` value the edit was made from, a rule to
    remove must still be there, and a list must still lack every value the edit adds (a list that gained any of them
    moved under the proposal). Anything else refuses as stale; nothing is written either way. Returns the edited
    text, so the edits are applied once."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise _stale(e) from None
    for e in edits:
        if e.get("kind") == "list_add":
            have = {str(x).casefold() for x in (raw.get("lists") or {}).get(e.get("list"), None) or ()}
            already = sorted(v for v in e.get("values") or () if str(v).casefold() in have)
            if already:
                raise Stale(f"{STALE} ([lists] {e.get('list')} already has {', '.join(already)})")
    try:
        return rulesedit.apply_edits(text, edits)
    except (rulesedit.EditError, ValueError) as e:
        raise _stale(e) from None


def _keeps_project_profiles(path: Path, new: str, root: Path) -> None:
    """Every profile the project config names that loads with the current ruleset still does with `new`: a
    rule removed while a project profile lists it in `[rules] disabled` would leave that profile unloadable, so it
    refuses (not stale: the proposal stays approved) until the rule is taken out of the list. A profile that already
    fails isn't this apply's to judge."""
    try:
        refs = config.project_profile_refs(root)
        old_cfg = registry.load_config(path)
    except (ValueError, OSError):
        return
    if not refs:
        return
    new_cfg = rulesedit.load_text(new)
    for ref in refs:
        try:
            prof = _profile.load(ref, search=(Path(root) / ".plainspoken" / "profiles",))
            old_cfg.check_profile(prof)
        except (ValueError, OSError):
            continue
        try:
            new_cfg.check_profile(prof)
        except ValueError as e:
            raise Refused(f"the edited ruleset breaks the project profile {prof.name!r} ({_first_line(e)}): take "
                          "the rule out of its [rules] disabled first, then apply again") from None


def _own_profile(p: Mapping, root: Path):
    """The profile the proposal was made for (its `profile` name), as a project file: among the profiles the project
    config names and the files in .plainspoken/profiles/, the one whose [profile] name it is. Not the profile the
    project resolves now (PLAINSPOKEN_PROFILE, [engine] profile): with per-folder profiles that may be another one.
    Refuses, naming it, when the proposal names no profile, or no project file (or more than one) has that name."""
    name = p.get("profile")
    if not isinstance(name, str) or not name:
        raise Refused(f"{p.get('id')} doesn't name the profile it was made for (calibrate had no profile), so "
                      "apply won't guess one: reject it, or apply it to a ruleset checkout with --rules")
    folder = Path(root) / ".plainspoken" / "profiles"
    try:
        refs = config.project_profile_refs(root)
    except (ValueError, OSError) as e:
        raise Refused(f"can't read the project config ({_first_line(e)})") from None
    found, broken = {}, []
    for ref in [*refs, *(str(f) for f in sorted(folder.glob("*.toml")))]:
        try:
            prof = _profile.load(ref, search=(folder,))
        except (ValueError, OSError) as e:
            if Path(ref).stem == name:
                broken.append(f"{ref}: {_first_line(e)}")
            continue
        src = Path(prof.source).resolve()
        if prof.name == name and src.is_relative_to(Path(root).resolve()):
            found.setdefault(src, prof)
    if len(found) > 1:
        raise Refused(f"more than one project file has the profile name {name!r} "
                      f"({', '.join(str(f) for f in found)}): give each its own name, then apply again")
    if not found:
        why = f" (it doesn't load: {broken[0]})" if broken else ""
        raise Refused(f"the proposal's profile {name!r} isn't a project file{why}: copy it into "
                      f".plainspoken/profiles/{name}.toml first, then apply again")
    return next(iter(found.values()))


def _edit(p: dict, path: Path, text: str, target: str, rebased: bool, root: Path, settings: Mapping) -> tuple:
    """(out path, old text, new text, version, changelog, changelog title, entry heading) for the edit `apply` would
    write. Raises `Stale` when an edit no longer applies and `Refused` for anything else; writes nothing."""
    if target == "ruleset":
        try:  # a target that doesn't load is a broken file, not a stale proposal
            current = registry.load_config(path).version
        except (ValueError, OSError) as e:
            raise Refused(f"{path}: the ruleset doesn't load ({_first_line(e)})") from None
        edited = _rebase_check(text, p["edits"]) if rebased else None
        try:
            version = rulesedit.bump(current, p.get("bump") or "minor")
            new = rulesedit.set_version(edited if edited is not None else rulesedit.apply_edits(text, p["edits"]),
                                        version)
        except (rulesedit.EditError, ValueError) as e:
            raise _stale(e) from None
        _keeps_project_profiles(path, new, root)
        return path, text, new, version, path.parent / CHANGELOG, CHANGELOG_TITLE, version
    try:
        cfg = registry.load_config(path)
    except (ValueError, OSError) as e:
        raise Refused(f"{path}: the ruleset doesn't load ({_first_line(e)})") from None
    prof = _own_profile(p, root)
    out_path = Path(prof.source)
    try:
        old_text = out_path.read_text(encoding="utf-8")
    except OSError as e:
        raise Refused(f"{out_path}: can't read the profile ({e})") from None
    try:
        new = rulesedit.apply_profile_edits(old_text, p["edits"], cfg)
    except rulesedit.EditError as e:
        raise _stale(e) from None
    return (out_path, old_text, new, cfg.version, Path(settings["proposals_dir"]) / "CHANGELOG.md",
            PROFILE_CHANGELOG_TITLE, f"profile {prof.name}")


RUBRICS = ("judges.md", "judge-inline.md")  # the rubric files beside a ruleset (`<ruleset folder>/rubrics/`)


def rubric_notes(edits: Iterable[Mapping], rules_path: Path) -> list[str]:
    """For each `rule_remove` whose rule still has a `### <id> ` section in a rubric beside the ruleset, a line
    naming it: apply never edits the rubrics (a rubric change goes by a normal commit), so the person removes the
    section by hand in the same change."""
    out = []
    for e in edits:
        if e.get("kind") != "rule_remove":
            continue
        rid = str(e.get("rule"))
        heading = re.compile(rf"^### {re.escape(rid)} .*$", re.M)
        for name in RUBRICS:
            path = Path(rules_path).parent / "rubrics" / name
            try:
                m = heading.search(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if m:
                out.append(f"{path} still has the rubric section `{m.group(0)}`: remove it by hand in the same "
                           "change (kaizen never edits the rubrics)")
    return out


def apply(pid: str, root: Path, settings: Mapping, rules_path: Path | None = None, target: str = "ruleset",
          dry_run: bool = False, *, now: datetime | None = None) -> dict:
    """Apply an approved proposal. Returns `{"id", "target", "path", "diff", "version", "changelog", "dry_run",
    "logged", "changelog_error", "rebased", "rubric_notes"}` (`rebased`: the ruleset changed since calibrate and the
    edits still applied; `rubric_notes`: the rubric sections a removed rule leaves behind). Raises `Refused`
    (nothing written), `Stale` (nothing written to the target; outside a dry run the proposal is recorded as
    superseded) or `UnknownProposal`."""
    now = datetime.now(timezone.utc) if now is None else now
    p = load(pid, settings)
    if not _intact(p):
        raise Refused(f"proposal file changed after it was made ({pid} no longer matches its id): restore it, or "
                      "reject it; calibrate revisits the rule when new evidence builds")
    if target not in TARGETS:
        raise Refused(f"--target must be one of {', '.join(TARGETS)}")
    if p.get("action") == "review" or not p.get("edits"):
        raise Refused(f"{pid} is a review proposal with no edits: make the change by hand in a PR")
    events = ledger.read(settings)[0]
    if applied(pid, events):
        raise Refused(f"{pid} is already applied: nothing to do")
    if superseded(pid, events) is not None:
        raise Refused(f"{pid} is superseded (a value it edits changed after it was approved): nothing to apply; "
                      "calibrate can propose for the rule again")
    d = decision(pid, events)
    if d is None:
        raise Refused(f"no recorded approval for {pid}: approve it through the adapter, then run `kaizen decisions`")
    approver = _approver(d)
    if d["outcome"] == "rejected":
        raise Refused(f"{pid} was rejected by {approver}: nothing to apply")
    if target not in (p.get("targets") or []):
        raise Refused(f"{pid} can't be applied to a profile: only a proposal made of threshold changes can")
    path = Path(rules_path) if rules_path is not None else default_rules()
    if rules_path is None and target == "ruleset" and _installed(path):
        raise Refused("this ruleset belongs to an installed plugin, so kaizen won't edit it: share the evidence "
                      "upstream with `kaizen report --share`, pass --rules <checkout>/data/rules.toml, or use "
                      "--target profile for a threshold change")
    try:
        data = path.read_bytes()
    except OSError as e:
        raise Refused(f"{path}: can't read the ruleset ({e})") from None
    text = data.decode("utf-8")
    rebased = hashlib.sha256(data).hexdigest() != p.get("base_sha256")
    date = now.astimezone(timezone.utc).date().isoformat()
    try:
        spent = _spent_by(p, events, target)
        if spent is not None:
            raise Stale(f"{STALE} (another proposal for rule {p.get('rule')} was applied since this one was made, "
                        f"{spent.get('proposal')}: the evidence it rests on is spent)")
        made = _edit(p, path, text, target, rebased, Path(root), settings)
    except Stale as e:
        try:
            seen = registry.load_config(path).version
        except (ValueError, OSError):
            seen = str(p.get("ruleset_version") or "unknown")
        raise _supersede(p, e, seen, approver, settings, now, dry_run) from None
    out_path, old_text, new, version, changelog, title, heading = made
    result = {"id": pid, "target": target, "path": str(out_path), "diff": rulesedit.diff(old_text, new, out_path.name),
              "version": version, "changelog": str(changelog), "dry_run": dry_run, "logged": False,
              "changelog_error": None, "rebased": rebased,
              "rubric_notes": rubric_notes(p["edits"], path) if target == "ruleset" else []}
    if dry_run:
        return result
    try:  # computed before anything is written: an unreadable changelog refuses with nothing changed
        log_text = _prepend(changelog, rulesedit.changelog_entry(heading, date, p, approver), title)
    except (OSError, UnicodeDecodeError) as e:
        raise Refused(f"{changelog}: can't read the changelog ({_first_line(e)})") from None
    # The target and its changelog go in as a pair: both are staged as temp files first, so a failure to write
    # either refuses with nothing changed; then two renames. Only a failure between the renames leaves the edit in
    # without its changelog entry, and that is reported as applied with `changelog_error`, never refused.
    try:
        staged = report.stage_atomic(out_path, new)
    except OSError as e:
        raise Refused(f"{out_path}: can't write ({_first_line(e)})") from None
    try:
        staged_log = report.stage_atomic(changelog, log_text)
    except OSError as e:
        Path(staged).unlink(missing_ok=True)
        raise Refused(f"{changelog}: can't write the changelog ({_first_line(e)}), so nothing was written") from None
    try:
        report.commit_staged(staged, out_path)
    except OSError as e:
        Path(staged_log).unlink(missing_ok=True)
        raise Refused(f"{out_path}: can't write ({_first_line(e)})") from None
    try:  # the edit is in: from here on it's reported as applied, never refused
        report.commit_staged(staged_log, changelog)
    except OSError as e:
        Path(staged_log).unlink(missing_ok=True)
        result["changelog_error"] = _first_line(e)
    result["logged"] = _log_apply(p, version, approver, settings, now, target)
    return result
