"""The `trello` adapter: one card per proposal through the Trello REST API, and decisions from the card's comments.

Requests go through an injectable `opener(request) -> (status, body_bytes)` (tests pass a fake); the default uses
`urllib` with a 30-second timeout. The key and token come from the environment variables `[kaizen.trello] key_env`
and `token_env` name, and travel only as query parameters on the request. They never appear in an error, a printed
line, the proposal file or the ledger: errors name the variable, and any text that came back is scrubbed of both
values first (scrubbed before any cut). Only unedited comments on the proposal's own card count, from an approver:
an `approvers` entry that is a member id matches `idMemberCreator` (immutable, preferred); any other entry matches
`memberCreator.username` case-insensitively. A comment decides only when its whole body is one plain decision
line (`adapters.parse_decision`), and the card description never counts.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from plainspoken.adapters import (Adapter, AdapterError, first_line, iso, looks_like_decision, near_misses,
                                  outward_decide, parse_decision, render, title)

API = "https://api.trello.com/1"
TIMEOUT = 30
NAME_MAX = 120
DESC_MAX = 16_000  # Trello's limit is 16,384 characters
_CARD = re.compile(r"[0-9A-Za-z]{8,64}")
_MEMBER = re.compile(r"[0-9a-fA-F]{24}")


def default_opener(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except OSError:
            body = b""
        return e.code, body


_decide = outward_decide  # the one `## Decide` text, shared with the other outward adapter


class TrelloAdapter(Adapter):
    name = "trello"
    SKIP_NOTE = "Trello didn't send enough to tell whether they were edited"

    def __init__(self, settings: Mapping, opener: Callable | None = None, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        tr = dict(settings.get("trello") or {})
        self.list_id = tr.get("list_id")
        if not self.list_id:
            raise AdapterError("[kaizen.trello] list_id isn't set: name the Trello list that gets the proposal cards")
        self.label_ids = [str(x) for x in tr.get("label_ids") or []]
        self.key_env, self.token_env = str(tr.get("key_env") or "TRELLO_API_KEY"), \
            str(tr.get("token_env") or "TRELLO_TOKEN")
        missing = [v for v in (self.key_env, self.token_env) if not (env.get(v) or "").strip()]
        if missing:
            raise AdapterError(f"the Trello adapter needs {' and '.join(missing)} set in the environment "
                               "(named by [kaizen.trello] key_env and token_env), so nothing was sent")
        self._key, self._token = env[self.key_env].strip(), env[self.token_env].strip()
        self.approvers = list(settings.get("approvers") or [])
        if not self.approvers:
            raise AdapterError("[kaizen] approvers is empty: name the Trello usernames whose comments may decide")
        self.opener = opener or default_opener

    def _scrub(self, text: str) -> str:
        for secret in (self._key, self._token):
            for form in {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}:
                text = text.replace(form, "***")
        return text

    def _url(self, path: str, **query: str) -> str:
        return f"{API}{path}?" + urllib.parse.urlencode({**query, "key": self._key, "token": self._token})

    def _send(self, request: urllib.request.Request, what: str) -> object:
        try:
            status, body = self.opener(request)
        except Exception as e:  # noqa: BLE001 (a network boundary: whatever it raises becomes one scrubbed line)
            raise AdapterError(f"Trello {what}: can't reach the API ({first_line(self._scrub(str(e)))[:200]})") \
                from None
        text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
        status = status if isinstance(status, int) else 0
        if not 200 <= status < 300:
            hint = (f": check the key and token in ${self.key_env} and ${self.token_env}"
                    if status in (401, 403) else "")
            # scrub first, then cut: a secret straddling the cut can't leave a prefix behind
            raise AdapterError(f"Trello {what} failed (HTTP {status}{hint}): "
                               f"{first_line(self._scrub(text or 'no message'))[:120]}")
        try:
            return json.loads(text)
        except ValueError:
            raise AdapterError(f"Trello {what}: the answer wasn't JSON") from None

    def emit_proposal(self, p: dict) -> str:
        """`POST /1/cards` (idList, name, desc, idLabels); the ref is the card id."""
        form = {"idList": str(self.list_id), "name": title(p, NAME_MAX),
                "desc": render(p, _decide(self.approvers), outward=True, max_chars=DESC_MAX), "pos": "top"}
        if self.label_ids:
            form["idLabels"] = ",".join(self.label_ids)
        request = urllib.request.Request(self._url("/cards"), data=urllib.parse.urlencode(form).encode("utf-8"),
                                         method="POST", headers={"Accept": "application/json",
                                                                 "Content-Type": "application/x-www-form-urlencoded"})
        data = self._send(request, "card create")
        card = data.get("id") if isinstance(data, dict) else None
        if not isinstance(card, str) or not _CARD.fullmatch(card):
            raise AdapterError("Trello card create: the answer had no card id")
        return card

    def _approver(self, action: dict) -> str | None:
        """The username of an approver who wrote `action`, or None. An `approvers` entry that is a Trello member id
        (24 hex) matches `idMemberCreator`, which never changes; any other entry matches the username, which a
        member can change (and someone else could then take), so member ids are the safer thing to list."""
        who = action.get("memberCreator") if isinstance(action.get("memberCreator"), dict) else {}
        user = who.get("username") if isinstance(who.get("username"), str) else ""
        member = action.get("idMemberCreator") or who.get("id")
        member = member if isinstance(member, str) else ""
        for a in self.approvers:
            a = str(a)
            if _MEMBER.fullmatch(a):
                if member and member.lower() == a.lower():
                    return user or member
            elif user and user.casefold() == a.casefold():
                return user
        return None

    def read_decisions(self, p: dict) -> list[dict]:
        """Decisions from the comments on the proposal's own card: the card description (the plugin's text) must
        name the proposal id, and each comment must belong to that card. Edited comments (`data.dateLastEdited`)
        don't count; the description never does."""
        ref = str(p.get("ref") or "")
        if not _CARD.fullmatch(ref):
            raise AdapterError(f"the proposal's trello ref {ref!r} isn't a card id")
        card = self._send(urllib.request.Request(self._url(f"/cards/{ref}", fields="desc"), method="GET",
                                                 headers={"Accept": "application/json"}), f"card {ref}")
        if not isinstance(card, dict) or f"**{p['id']}**" not in str(card.get("desc") or ""):
            raise AdapterError(f"Trello card {ref} isn't the one made for {p['id']} (its description doesn't name "
                               "it), so none of its comments can decide this proposal")
        url = self._url(f"/cards/{ref}/actions", filter="commentCard", limit="1000")
        request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        data = self._send(request, f"card {ref} comments")
        if not isinstance(data, list):
            raise AdapterError(f"Trello card {ref} comments: the answer wasn't a list")
        found, misses = [], []
        for a in data:
            if not isinstance(a, dict):
                continue
            body = a.get("data") if isinstance(a.get("data"), dict) else {}
            on = body.get("card") if isinstance(body.get("card"), dict) else {}
            if on.get("id") != ref:
                continue  # a comment on another card
            user = self._approver(a)
            if user is None:
                continue
            text = str(body.get("text") or "")
            parsed = parse_decision(text)
            if parsed is None:
                if looks_like_decision(text):  # an approver meant to decide: tell them to repost
                    misses.append((user, iso(a.get("date"))))
                continue
            # Trello marks an edit by adding data.dateLastEdited; a comment without the fields that frame it (its
            # type, date, text and author id) can't be read as unedited, so it's skipped (fail closed).
            if (a.get("type") != "commentCard" or iso(a.get("date")) is None or not isinstance(body.get("text"), str)
                    or not isinstance(a.get("idMemberCreator"), str) or not a.get("idMemberCreator")):
                self.skipped += 1
                continue
            if body.get("dateLastEdited"):
                continue
            found.append({"verdict": parsed[0], "by": user, "reason": parsed[1], "at": iso(a.get("date"))})
        self.near += near_misses(misses, found)
        return sorted(found, key=lambda d: d["at"] or "")  # Trello lists newest first
