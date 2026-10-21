"""Opt-in contact lifecycle check against the configured HighLevel test location."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from transcript_weaver_highlevel.driver import HighLevelClient, HighLevelDriver

from transcript_weaver.credentials import resolve_credential
from transcript_weaver.out.core import OutputError

LIVE_FLAG = "TRANSCRIPT_WEAVER_LIVE_HIGHLEVEL"
LOCATION_ENV = "TRANSCRIPT_WEAVER_HIGHLEVEL_LOCATION_ID"
TOKEN_ENV = "TRANSCRIPT_WEAVER_HIGHLEVEL_TOKEN"
TEST_NAME_PREFIX = "[TRW LIVE TEST]"
TEST_EMAIL_PREFIX = "trw-live-test-"


def _enabled() -> bool:
    return os.environ.get(LIVE_FLAG, "").casefold() in {"1", "true", "yes"}


def _owned(contact: Mapping[str, Any]) -> bool:
    name = contact.get("name")
    email = contact.get("email")
    source = contact.get("source")
    return (
        isinstance(name, str)
        and name.startswith(TEST_NAME_PREFIX)
        and isinstance(email, str)
        and email.startswith(TEST_EMAIL_PREFIX)
        and email.endswith("@example.invalid")
        and source == "Transcript Weaver"
    )


def _cleanup(client: HighLevelClient) -> None:
    for summary in client.list_contacts():
        summary_id = summary.get("id")
        if not isinstance(summary_id, str) or not summary_id:
            pytest.fail("HighLevel contact summary has no ID; cleanup stopped.")
        contact = client.get_contact(summary_id)
        if not _owned(contact):
            continue
        contact_id = contact.get("id")
        if not isinstance(contact_id, str) or not contact_id:
            pytest.fail("Owned HighLevel live-test contact has no ID; cleanup stopped.")
        try:
            client.delete_contact(contact_id)
        except OutputError as exc:
            pytest.fail(
                f"Could not delete owned HighLevel live-test contact {contact_id}; "
                f"cleanup stopped before creating more contacts: {exc}"
            )


def _profile(*, replace_first_name: bool = False) -> dict[str, Any]:
    first_name: dict[str, str] = {"target": "firstName"}
    if replace_first_name:
        first_name["on_conflict"] = "replace"
    return {
        "driver": "highlevel",
        "location_id": _credential_spec(LOCATION_ENV, "highlevel/ddr_locationid"),
        "token": _credential_spec(TOKEN_ENV, "highlevel/ddr_pit"),
        "source_path": "weave.linkedin",
        "identity": ["email"],
        "on_conflict": "review",
        "fields": {
            "full_name": {"target": "name"},
            "first_name": first_name,
            "last_name": {"target": "lastName"},
            "email": {"target": "email"},
        },
    }


def _credential_spec(environment: str, pass_entry: str) -> str:
    return (
        f"env({environment})" if os.environ.get(environment) else f"command(pass show {pass_entry})"
    )


def _packet(email: str, *, first: str, last: str | None = None) -> dict[str, Any]:
    linkedin = {
        "full_name": f"{TEST_NAME_PREFIX} {first}",
        "first_name": first,
        "email": email,
    }
    if last is not None:
        linkedin["last_name"] = last
    return {"weave": {"linkedin": linkedin}}


@pytest.mark.live_highlevel
@pytest.mark.skipif(not _enabled(), reason=f"set {LIVE_FLAG}=1 to enable")
def test_live_create_fill_review_replace_and_cleanup() -> None:
    location = resolve_credential(
        _credential_spec(LOCATION_ENV, "highlevel/ddr_locationid"),
        label="HighLevel location ID",
    )
    token = resolve_credential(
        _credential_spec(TOKEN_ENV, "highlevel/ddr_pit"),
        label="HighLevel token",
    )
    client = HighLevelClient(location, token)
    _cleanup(client)
    email = f"{TEST_EMAIL_PREFIX}{uuid.uuid4().hex}@example.invalid"
    driver = HighLevelDriver(lambda received_location, received_token: client)

    try:
        created = driver(
            _packet(email, first="Original"),
            _profile(),
            warning=lambda _: None,
        )
        assert created.operation == "created"

        unchanged = driver(
            _packet(email, first="Original"),
            _profile(),
            warning=lambda _: None,
        )
        assert unchanged.operation == "unchanged"

        filled = driver(
            _packet(email, first="Original", last="Person"),
            _profile(),
            warning=lambda _: None,
        )
        assert filled.operation == "updated"

        with pytest.raises(OutputError, match="different nonempty values"):
            driver(
                _packet(email, first="Replacement", last="Person"),
                _profile(),
                warning=lambda _: None,
            )

        replaced = driver(
            _packet(email, first="Replacement", last="Person"),
            _profile(replace_first_name=True),
            warning=lambda _: None,
        )
        assert replaced.operation == "updated"

        matches = [contact for contact in client.list_contacts() if contact.get("email") == email]
        assert len(matches) == 1
        final = client.get_contact(str(matches[0]["id"]))
        assert final.get("firstName") == "Replacement"
        assert final.get("lastName") == "Person"
    finally:
        _cleanup(client)
