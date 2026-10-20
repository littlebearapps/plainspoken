"""A stdlib JSON-Schema subset: just the keywords the claim-ledger, reader-value and report schemas use.

`validate(instance, schema)` returns `"<dotted.path or <root>>: <message>"` strings sorted by path, `[]` when valid.
The whole schema is checked before any instance is: a keyword outside the subset raises `SchemaError`, even in a
branch the instance never reaches. Fail closed, never skip.

`additionalProperties` is `false` or a schema every key outside `properties` must match (a map such as the
report's `rules`); `true` isn't supported. `datetime.date`/`datetime.datetime`/`datetime.time` values (TOML's
unquoted dates and times) are compared as their `isoformat()` strings, and `bool` is never an `integer` or a
`number`. A `date-time` needs its UTC offset (`Z` or `+10:00`), as RFC 3339 says. A `$ref` cycle that never reaches
into the instance (`a` -> `b` -> `a` through `$ref`, `allOf`, `if` or `then`) is a SchemaError. Error messages never
raise on an odd value.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "data" / "schemas"
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ANNOTATIONS = {"$schema", "$id", "title", "description"}
_KEYWORDS = {"type", "properties", "required", "additionalProperties", "enum", "const", "pattern", "minLength",
             "minItems", "items", "$ref", "$defs", "allOf", "if", "then", "dependentRequired", "format"}
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool,
          "null": type(None)}
_FORMATS = ("date", "date-time")
_REF = re.compile(r"^#/\$defs/([^/]+)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}")


class SchemaError(ValueError):
    """The schema itself can't be used: an unsupported keyword, a bad value or an unresolvable `$ref`."""


def load(name: str) -> dict:
    """Read `data/schemas/<name>.schema.json` and check every keyword in it is supported."""
    if not isinstance(name, str) or not _NAME.match(name):
        raise SchemaError(f"bad schema name {name!r}")
    path = SCHEMAS_DIR / f"{name}.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SchemaError(f"{path.name}: can't read the schema ({type(e).__name__})") from None
    if not isinstance(schema, dict):
        raise SchemaError(f"{path.name}: the schema isn't an object")
    check_schema(schema)
    return schema


def check_schema(schema: dict) -> None:
    """Raise `SchemaError` if any keyword anywhere in `schema` is outside the subset or malformed, or a `$ref` cycle
    would loop without reaching into the instance."""
    _walk(schema, schema, "#")
    _check_ref_cycles(schema)


def _same_place_refs(node: object) -> list[str]:
    """The `$defs` names `node` applies to the same instance value: through `$ref`, `allOf`, `if` and `then`, never
    through `properties`, `items` or `additionalProperties` (those reach into the instance, so they end)."""
    out: list[str] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if not isinstance(n, dict):
            continue
        m = _REF.match(n["$ref"]) if isinstance(n.get("$ref"), str) else None
        if m:
            out.append(m.group(1))
        stack += [*(n.get("allOf") if isinstance(n.get("allOf"), list) else []), n.get("if"), n.get("then")]
    return out


def _check_ref_cycles(root: dict) -> None:
    defs = root.get("$defs") if isinstance(root.get("$defs"), dict) else {}
    edges = {name: _same_place_refs(sub) for name, sub in defs.items()}
    done: set[str] = set()

    def visit(name: str, trail: list[str]) -> None:
        if name in trail:
            loop = " -> ".join(f"#/$defs/{n}" for n in [*trail[trail.index(name):], name])
            raise SchemaError(f"cyclic $ref: {loop} never reaches into the instance")
        if name in done or name not in edges:
            return
        for nxt in edges[name]:
            visit(nxt, [*trail, name])
        done.add(name)

    for name in edges:
        visit(name, [])


def validate(instance: object, schema: dict) -> list[str]:
    """Validate `instance` against `schema`; return the errors sorted by path, `[]` when valid."""
    check_schema(schema)
    errors: list[tuple[tuple, str]] = []
    _check(_plain(instance), schema, (), schema, errors)
    errors.sort(key=lambda e: tuple((0, p, "") if isinstance(p, int) else (1, 0, p) for p in e[0]))
    return [f"{'.'.join(map(str, path)) or '<root>'}: {message}" for path, message in errors]


def _plain(value: object) -> object:
    if isinstance(value, (dt.date, dt.time)):  # datetime is a date subclass; TOML local times are dt.time
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _show(value: object) -> str:
    """A value for an error message. Never raises: a value JSON can't encode (a non-text key, a circular list)
    falls back to `repr()`, and one whose repr fails to its type name."""
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError, RecursionError):
        try:
            return repr(value)
        except Exception:  # a broken __repr__: still never raise from an error message
            return f"<{type(value).__name__}>"


def _walk(node: object, root: dict, where: str) -> None:
    if not isinstance(node, dict):
        raise SchemaError(f"{where}: a schema must be an object")
    unknown = sorted(set(node) - _KEYWORDS - _ANNOTATIONS)
    if unknown:
        raise SchemaError(f"{where}: unsupported keyword(s) {', '.join(unknown)}")
    if "type" in node:
        names = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not names or any(not isinstance(n, str) or n not in _TYPES for n in names):
            raise SchemaError(f"{where}: unsupported type {_show(node['type'])}")
    extra = node.get("additionalProperties", False)
    if extra is not False and not isinstance(extra, dict):
        raise SchemaError(f"{where}: additionalProperties must be false or a schema")
    if isinstance(extra, dict):
        _walk(extra, root, f"{where}/additionalProperties")
    if "required" in node and not _strings(node["required"]):
        raise SchemaError(f"{where}: required must be a list of strings")
    if "enum" in node and not isinstance(node["enum"], list):
        raise SchemaError(f"{where}: enum must be a list")
    for key in ("minLength", "minItems"):
        if key in node and (isinstance(node[key], bool) or not isinstance(node[key], int) or node[key] < 0):
            raise SchemaError(f"{where}: {key} must be a non-negative integer")
    if "pattern" in node:
        try:
            re.compile(node["pattern"])
        except (TypeError, re.error):
            raise SchemaError(f"{where}: bad pattern {node['pattern']!r}") from None
    if "format" in node and node["format"] not in _FORMATS:
        raise SchemaError(f"{where}: unsupported format {node['format']!r}")
    if "$ref" in node:
        _resolve(node["$ref"], root)
    if "dependentRequired" in node:
        deps = node["dependentRequired"]
        if not isinstance(deps, dict) or not all(_strings(v) for v in deps.values()):
            raise SchemaError(f"{where}: dependentRequired must map keys to lists of strings")
    for key in ("properties", "$defs"):
        if key in node:
            if not isinstance(node[key], dict):
                raise SchemaError(f"{where}: {key} must be an object")
            for name, sub in node[key].items():
                _walk(sub, root, f"{where}/{key}/{name}")
    if "allOf" in node:
        if not isinstance(node["allOf"], list):
            raise SchemaError(f"{where}: allOf must be a list")
        for i, sub in enumerate(node["allOf"]):
            _walk(sub, root, f"{where}/allOf/{i}")
    for key in ("items", "if", "then"):
        if key in node:
            _walk(node[key], root, f"{where}/{key}")


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _resolve(ref: object, root: dict) -> dict:
    m = _REF.match(ref) if isinstance(ref, str) else None
    if not m:
        raise SchemaError(f"unsupported $ref {ref!r}: only #/$defs/<name>")
    target = root.get("$defs", {}).get(m.group(1)) if isinstance(root.get("$defs"), dict) else None
    if not isinstance(target, dict):
        raise SchemaError(f"$ref {ref!r} doesn't resolve")
    return target


def _type_name(value: object) -> str:
    for name in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if _is(value, name):
            return name
    return type(value).__name__


def _is(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return name == "boolean"
    return isinstance(value, _TYPES[name])


def _same(a: object, b: object) -> bool:
    """JSON equality: `True` never equals `1`."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if _is(a, "number") and _is(b, "number"):
        return a == b
    return type(a) is type(b) and a == b


def _check(value: object, schema: dict, path: tuple, root: dict, errors: list) -> None:
    def err(message: str) -> None:
        errors.append((path, message))

    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), path, root, errors)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is(value, n) for n in names):
            return err(f"expected {' or '.join(names)}, got {_type_name(value)}")
    if "enum" in schema and not any(_same(value, v) for v in schema["enum"]):
        err(f"{_show(value)} is not one of {_show(schema['enum'])}")
    if "const" in schema and not _same(value, schema["const"]):
        err(f"must be {_show(schema['const'])}")
    if isinstance(value, str):
        _check_string(value, schema, err)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            err(f"needs at least {schema['minItems']} item(s), has {len(value)}")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(item, schema["items"], path + (i,), root, errors)
    if isinstance(value, dict):
        _check_object(value, schema, path, root, errors, err)
    for sub in schema.get("allOf", []):
        _check(value, sub, path, root, errors)
    if "if" in schema and "then" in schema:
        trial: list = []
        _check(value, schema["if"], path, root, trial)
        if not trial:
            _check(value, schema["then"], path, root, errors)


def _check_string(value: str, schema: dict, err) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        err(f"needs at least {schema['minLength']} character(s), has {len(value)}")
    if "pattern" in schema and not re.search(schema["pattern"], value):
        err(f"{_show(value)} doesn't match {schema['pattern']!r}")
    fmt = schema.get("format")
    if fmt and not _valid_format(value, fmt):
        err(f"{_show(value)} isn't a valid {fmt}")


def _valid_format(value: str, fmt: str) -> bool:
    try:
        if fmt == "date":
            return bool(_DATE.match(value)) and dt.date.fromisoformat(value) is not None
        stamp = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        return bool(_DATE_TIME.match(value)) and dt.datetime.fromisoformat(stamp).tzinfo is not None
    except ValueError:
        return False


def _check_object(value: dict, schema: dict, path: tuple, root: dict, errors: list, err) -> None:
    for key in schema.get("required", []):
        if key not in value:
            err(f"missing required key {key!r}")
    props = schema.get("properties", {})
    extra = schema.get("additionalProperties")
    for key in value:
        if key in props:
            continue
        if extra is False:
            err(f"unexpected key {key!r}")
        elif isinstance(extra, dict):
            _check(value[key], extra, path + (key,), root, errors)
    for key, sub in props.items():
        if key in value:
            _check(value[key], sub, path + (key,), root, errors)
    for key, needs in schema.get("dependentRequired", {}).items():
        if key in value:
            for need in needs:
                if need not in value:
                    err(f"{key!r} needs {need!r}")
