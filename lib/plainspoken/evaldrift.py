"""Model drift between two judge-validation runs (plan 8.4): `eval drift --run NEW --against OLD`.

`load` reads a run folder `eval judges` wrote (`summary.json`, and `run.json` when it's there). `compare` lines the two
runs up per group and judge (each model, and each majority row) on one split, and for TPR, TNR and precision gives
both runs' rates with their 95% Wilson intervals and a change: `drop` (the new interval sits entirely below the old),
`rise` (entirely above), `overlap` (the change could be noise) or `n/a` (no cases on a side).

Flags: a drop; a model whose id changed (asked for, or answered as); a group only one run has. Notes: a judge only one
run has, a changed golden set or filters, a run that stopped early, provisional labels. `render` writes the markdown
report. Free: it reads files only. No composite score."""
from __future__ import annotations

import json
from pathlib import Path

from plainspoken import evaljudges

SCHEMA = 1
METRICS = ("tpr", "tnr", "precision")
LABELS = {"tpr": "TPR", "tnr": "TNR", "precision": "precision"}
_EPS = 1e-9


class DriftError(ValueError):
    pass


def _read(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def load(folder: Path) -> dict:
    """The facts `compare` needs from one run folder. DriftError when it has no readable judge-validation summary."""
    folder = Path(folder)
    summary = _read(folder / "summary.json")
    if not (isinstance(summary, dict) and isinstance(summary.get("groups"), dict)
            and isinstance(summary.get("models"), list)):
        raise DriftError(f"{folder / 'summary.json'}: no readable judge-validation summary (run `eval judges` first)")
    meta = _read(folder / "run.json")
    meta = meta if isinstance(meta, dict) else {}
    run = summary.get("run") if isinstance(summary.get("run"), dict) else {}
    ids = meta.get("model_ids") if isinstance(meta.get("model_ids"), dict) else {}
    models = {}
    for m in summary["models"]:
        if isinstance(m, dict) and isinstance(m.get("name"), str):
            models[m["name"]] = {"requested": m.get("model_requested") or ids.get(m["name"]),
                                 "reported": m.get("model_reported")}
    return {"id": run.get("id") or folder.name, "dir": str(folder), "scored": run.get("scored"),
            "golden_sha256": run.get("golden_sha256") or meta.get("golden_sha256"),
            "golden_cases": run.get("golden_cases") or meta.get("golden_cases"),
            "filters": run.get("filters") if "filters" in run else meta.get("filters"),
            "stopped": run.get("stopped"), "models": models, "groups": summary["groups"]}


def change(old_ci: list | None, new_ci: list | None) -> str:
    """`drop`, `rise` or `overlap` from two intervals; `n/a` when either is missing."""
    if not old_ci or not new_ci:
        return "n/a"
    if new_ci[1] < old_ci[0] - _EPS:
        return "drop"
    if new_ci[0] > old_ci[1] + _EPS:
        return "rise"
    return "overlap"


def _judges(split: dict) -> dict[str, dict]:
    rows = dict(split.get("models") or {})
    rows.update({f"majority: {t}": r for t, r in (split.get("majority") or {}).items()})
    return rows


def _fmt(r: dict | None) -> str:
    return "not in this run" if r is None else evaljudges._rate(r)


def _id_change(name: str, old: dict, new: dict) -> str | None:
    parts = []
    if old.get("requested") != new.get("requested"):
        parts.append(f"asked for {old.get('requested') or 'not recorded'} → {new.get('requested') or 'not recorded'}")
    o, n = old.get("reported"), new.get("reported")
    if o and n and o != n:  # None is "not run" and "" is "not reported": neither says the model changed
        parts.append(f"answered as {o} → {n}")
    return f"{name}: " + "; ".join(parts) if parts else None


def compare(new: dict, old: dict, split: str = "all") -> dict:
    """Every rate both runs have on `split`, with its change, plus the flags and notes (see the module text)."""
    if split not in evaljudges.SPLITS:
        raise DriftError(f"split {split!r} isn't one of {', '.join(evaljudges.SPLITS)}")
    flags: list[dict] = []
    notes: list[str] = []
    rows: list[dict] = []
    for name in [n for n in new["models"] if n in old["models"]]:
        text = _id_change(name, old["models"][name], new["models"][name])
        if text:
            flags.append({"type": "model_changed", "judge": name, "text": f"model id changed: {text}"})
    groups = list(dict.fromkeys([*old["groups"], *new["groups"]]))
    for g in groups:
        if g not in new["groups"] or g not in old["groups"]:
            side = "old" if g in old["groups"] else "new"
            flags.append({"type": "missing_group", "group": g,
                          "text": f"{g}: only in the {side} run, so not compared"})
            continue
        try:
            o_split, n_split = old["groups"][g]["splits"][split], new["groups"][g]["splits"][split]
        except (KeyError, TypeError):
            raise DriftError(f"group {g} has no {split!r} split in one of the runs") from None
        if o_split.get("proxy") or n_split.get("proxy"):
            notes.append(f"{g}: provisional labels on the {split} split, so its rates are a proxy")
        o_rows, n_rows = _judges(o_split), _judges(n_split)
        for judge in dict.fromkeys([*o_rows, *n_rows]):
            if judge not in o_rows or judge not in n_rows:
                side = "old" if judge in o_rows else "new"
                notes.append(f"{g} · {judge}: only in the {side} run, so not compared")
                continue
            for metric in METRICS:
                o, n = o_rows[judge][metric], n_rows[judge][metric]
                how = change(o["ci"] if o.get("n") else None, n["ci"] if n.get("n") else None)
                rows.append({"group": g, "judge": judge, "metric": metric, "old": o, "new": n, "change": how})
                if how == "drop":
                    flags.append({"type": "drop", "group": g, "judge": judge, "metric": metric,
                                  "text": f"{g} · {judge} · {LABELS[metric]} dropped: {_fmt(o)} → {_fmt(n)}"})
    if old.get("golden_sha256") != new.get("golden_sha256"):
        notes.append(f"the golden set changed between the runs ({old.get('golden_cases') or '?'} → "
                     f"{new.get('golden_cases') or '?'} cases): a change may come from the cases, not the models")
    if old.get("filters") != new.get("filters"):
        notes.append("the runs used different --group/--status filters")
    for side, run in (("old", old), ("new", new)):
        if run.get("stopped"):
            notes.append(f"the {side} run stopped early ({run['stopped']}), so its figures are partial")
    if old.get("dir") and old.get("dir") == new.get("dir"):
        notes.append("both sides are the same run folder")
    keep = ("id", "dir", "scored", "golden_sha256", "golden_cases", "filters", "stopped", "models")
    return {"schema": SCHEMA, "split": split, "new": {k: new.get(k) for k in keep},
            "against": {k: old.get(k) for k in keep}, "flags": flags, "notes": notes, "rows": rows}


def _side(title: str, run: dict) -> str:
    sha = (run.get("golden_sha256") or "")[:12]
    golden = f"golden {sha}… ({run.get('golden_cases') or '?'} cases)" if sha else "golden set not recorded"
    ids = ", ".join(f"{n} = {m.get('reported') or m.get('requested') or '?'}" for n, m in run["models"].items())
    return f"- {title}: {run['id']} · scored {run.get('scored') or 'unknown'} · {golden} · {ids or 'no models'}"


def render(d: dict) -> str:
    split = "all cases" if d["split"] == "all" else "human labels (confirmed + endorsed)"
    lines = [f"# Judge drift: {d['new']['id']} against {d['against']['id']}", "",
             _side("New", d["new"]), _side("Old", d["against"]),
             f"- Split: {split}. A drop is flagged only when the new 95% Wilson interval sits entirely below the old "
             "one; overlapping intervals could be noise, so the table shows every change and flags none of them.",
             "", f"## Flags ({len(d['flags'])})", ""]
    lines += [f"- {f['text']}" for f in d["flags"]] or ["None."]
    if d["notes"]:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in d["notes"]]
    lines += ["", "## Rates", ""]
    if d["rows"]:
        lines += ["| group | judge | metric | old [95% CI] | new [95% CI] | change |", "|---|---|---|---|---|---|"]
        lines += [f"| {r['group']} | {r['judge']} | {LABELS[r['metric']]} | {_fmt(r['old'])} | {_fmt(r['new'])} | "
                  f"{r['change']} |" for r in d["rows"]]
    else:
        lines.append("Nothing both runs measured.")
    return "\n".join(lines) + "\n"
