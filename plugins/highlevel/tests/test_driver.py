from __future__ import annotations

import io
import json
import urllib.error
from collections.abc import Mapping
from typing import Any

import pytest
from transcript_weaver_highlevel.driver import HighLevelClient, HighLevelDriver

from transcript_weaver.out.core import OutputError


class FakeClient:
    def __init__(
        self,
        *,
        contacts: list[Mapping[str, Any]] | None = None,
        full_contacts: dict[str, Mapping[str, Any]] | None = None,
        custom_fields: list[Mapping[str, Any]] | None = None,
    ) -> None:
        self.contacts = contacts or []
        self.full_contacts = full_contacts or {}
        self.custom_fields = custom_fields or []
        self.creates: list[Mapping[str, Any]] = []
        self.updates: list[tuple[str, Mapping[str, Any]]] = []

    def list_custom_fields(self) -> list[Mapping[str, Any]]:
        return self.custom_fields

    def list_contacts(self) -> list[Mapping[str, Any]]:
        return self.contacts

    def get_contact(self, contact_id: str) -> Mapping[str, Any]:
        return self.full_contacts[contact_id]

    def create_contact(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        self.creates.append(body)
        return {"contact": {"id": "created-id"}}

    def update_contact(self, contact_id: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        self.updates.append((contact_id, body))
        return {"contact": {"id": contact_id}}


def profile() -> dict[str, Any]:
    return {
        "driver": "highlevel",
        "location_id": "env(TEST_HIGHLEVEL_LOCATION)",
        "token": "env(TEST_HIGHLEVEL_TOKEN)",
        "source_path": "weave.linkedin",
        "identity": ["linkedin_url", "email", "phone"],
        "on_conflict": "review",
        "fields": {
            "full_name": {"target": "name"},
            "first_name": {"target": "firstName"},
            "last_name": {"target": "lastName"},
            "headline": {"target": {"custom_field": "contact.linkedin_headline"}},
            "about": {"target": {"custom_field": "contact.linkedin_about"}},
            "location": {"target": {"custom_field": "contact.linkedin_location"}},
            "email": {"target": "email"},
            "phone": {"target": "phone"},
            "linkedin_url": {"target": {"custom_field": "contact.linkedin_url"}},
        },
    }


def packet(**fields: str) -> dict[str, Any]:
    return {"weave": {"linkedin": fields}}


def definitions() -> list[Mapping[str, Any]]:
    return [
        {"id": "headline-id", "name": "LinkedIn Headline", "fieldKey": "contact.linkedin_headline"},
        {"id": "about-id", "name": "LinkedIn About", "fieldKey": "contact.linkedin_about"},
        {"id": "location-id", "name": "LinkedIn Location", "fieldKey": "contact.linkedin_location"},
        {"id": "url-id", "name": "LinkedIn URL", "fieldKey": "contact.linkedin_url"},
    ]


@pytest.fixture(autouse=True)
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_HIGHLEVEL_LOCATION", "location-id")
    monkeypatch.setenv("TEST_HIGHLEVEL_TOKEN", "secret-token")


def driver(client: FakeClient) -> HighLevelDriver:
    def factory(location: str, token: str) -> FakeClient:
        assert location == "location-id"
        assert token == "secret-token"
        return client

    return HighLevelDriver(factory)


def test_new_contact_maps_standard_and_custom_fields() -> None:
    client = FakeClient(custom_fields=definitions())
    result = driver(client)(
        packet(
            full_name="David Example",
            first_name="David",
            last_name="Example",
            headline="Engineer",
            linkedin_url="https://www.linkedin.com/in/david-example/",
        ),
        profile(),
        warning=lambda _: None,
    )

    assert result.operation == "created"
    assert client.updates == []
    assert client.creates == [
        {
            "locationId": "location-id",
            "source": "Transcript Weaver",
            "name": "David Example",
            "firstName": "David",
            "lastName": "Example",
            "customFields": [
                {"id": "headline-id", "fieldValue": "Engineer"},
                {
                    "id": "url-id",
                    "fieldValue": "https://www.linkedin.com/in/david-example/",
                },
            ],
        }
    ]


def test_unknown_source_field_requires_mapping_or_ignore() -> None:
    client = FakeClient(custom_fields=definitions())
    with pytest.raises(OutputError, match="Unmapped fields: newly_added"):
        driver(client)(
            packet(email="david@example.com", newly_added="surprise"),
            profile(),
            warning=lambda _: None,
        )
    assert client.creates == []


def test_explicit_ignore_allows_known_source_field() -> None:
    configured = profile()
    configured["fields"]["unneeded"] = {"ignore": True}
    client = FakeClient(custom_fields=definitions())

    driver(client)(
        packet(email="david@example.com", unneeded="not sent"),
        configured,
        warning=lambda _: None,
    )

    assert "unneeded" not in client.creates[0]


def test_duplicate_configured_destination_aborts_before_credentials_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = profile()
    configured["fields"]["headline"] = {"target": {"custom_field": "CONTACT.LINKEDIN_URL"}}
    monkeypatch.delenv("TEST_HIGHLEVEL_LOCATION")

    with pytest.raises(OutputError) as caught:
        driver(FakeClient())(
            packet(linkedin_url="https://www.linkedin.com/in/david/"),
            configured,
            warning=lambda _: None,
        )

    message = str(caught.value)
    assert "'headline' and 'linkedin_url' map to the same destination" in message
    assert "Every non-ignored source field must have a unique destination" in message


def test_custom_field_aliases_cannot_resolve_to_the_same_destination() -> None:
    configured = profile()
    configured["fields"]["headline"] = {"target": {"custom_field": "LinkedIn URL"}}
    client = FakeClient(custom_fields=definitions())

    with pytest.raises(OutputError) as caught:
        driver(client)(
            packet(linkedin_url="https://www.linkedin.com/in/david/"),
            configured,
            warning=lambda _: None,
        )

    message = str(caught.value)
    assert "'headline' and 'linkedin_url' resolve to the same custom field" in message
    assert "LinkedIn URL" in message
    assert client.creates == [] and client.updates == []


def test_same_values_do_nothing_and_url_is_normalized() -> None:
    listed = {
        "id": "existing-id",
        "email": "DAVID@example.com",
        "customFields": [{"id": "url-id", "value": "https://linkedin.com/in/david-example"}],
    }
    full = dict(listed)
    client = FakeClient(
        contacts=[listed],
        full_contacts={"existing-id": full},
        custom_fields=definitions(),
    )

    result = driver(client)(
        packet(
            email="david@example.com",
            linkedin_url="https://www.linkedin.com/in/David-Example/?tracking=removed",
        ),
        profile(),
        warning=lambda _: None,
    )

    assert result.operation == "unchanged"
    assert client.creates == [] and client.updates == []


def test_empty_target_is_filled_without_clearing_missing_input() -> None:
    listed = {"id": "existing-id", "email": "david@example.com"}
    full = {
        "id": "existing-id",
        "email": "david@example.com",
        "firstName": "",
        "lastName": "Existing",
    }
    client = FakeClient(
        contacts=[listed],
        full_contacts={"existing-id": full},
        custom_fields=definitions(),
    )

    result = driver(client)(
        packet(email="david@example.com", first_name="David"),
        profile(),
        warning=lambda _: None,
    )

    assert result.operation == "updated"
    assert client.updates == [("existing-id", {"firstName": "David"})]
    assert "lastName" not in client.updates[0][1]


def test_different_nonempty_value_aborts_entire_update_for_review() -> None:
    listed = {"id": "existing-id", "email": "david@example.com"}
    full = {
        "id": "existing-id",
        "email": "david@example.com",
        "firstName": "Dave",
        "lastName": "",
    }
    client = FakeClient(
        contacts=[listed],
        full_contacts={"existing-id": full},
        custom_fields=definitions(),
    )

    with pytest.raises(OutputError) as caught:
        driver(client)(
            packet(email="david@example.com", first_name="David", last_name="Example"),
            profile(),
            warning=lambda _: None,
        )
    assert str(caught.value) == (
        "HighLevel contact has different nonempty values:\n"
        "Field: first_name\n"
        'HighLevel value: "Dave"\n'
        'Incoming TRW value: "David"\n'
        "No contact was changed.\n"
        "Review the values or configure on_conflict as preserve or replace."
    )
    assert client.updates == []


def test_per_field_replace_and_preserve_are_explicit() -> None:
    configured = profile()
    configured["fields"]["first_name"]["on_conflict"] = "replace"
    configured["fields"]["last_name"]["on_conflict"] = "preserve"
    listed = {"id": "existing-id", "email": "david@example.com"}
    full = {
        "id": "existing-id",
        "email": "david@example.com",
        "firstName": "Dave",
        "lastName": "Old",
    }
    client = FakeClient(
        contacts=[listed],
        full_contacts={"existing-id": full},
        custom_fields=definitions(),
    )

    driver(client)(
        packet(email="david@example.com", first_name="David", last_name="Example"),
        configured,
        warning=lambda _: None,
    )

    assert client.updates == [("existing-id", {"firstName": "David"})]


def test_ambiguous_identity_aborts_before_read_or_write() -> None:
    contacts = [
        {"id": "one", "email": "david@example.com"},
        {
            "id": "two",
            "customFields": [{"id": "url-id", "value": "https://linkedin.com/in/david"}],
        },
    ]
    client = FakeClient(
        contacts=contacts,
        full_contacts={"one": contacts[0], "two": contacts[1]},
        custom_fields=definitions(),
    )

    with pytest.raises(OutputError, match="match multiple contacts"):
        driver(client)(
            packet(
                email="david@example.com",
                linkedin_url="https://www.linkedin.com/in/david/",
            ),
            profile(),
            warning=lambda _: None,
        )
    assert client.creates == [] and client.updates == []


def test_name_alone_never_matches_an_existing_contact() -> None:
    existing = {
        "id": "existing-id",
        "name": "David Example",
        "email": "someone-else@example.com",
    }
    client = FakeClient(
        contacts=[{"id": "existing-id"}],
        full_contacts={"existing-id": existing},
        custom_fields=definitions(),
    )

    result = driver(client)(
        packet(full_name="David Example", email="new-person@example.com"),
        profile(),
        warning=lambda _: None,
    )

    assert result.operation == "created"
    assert len(client.creates) == 1


def test_additional_email_identity_prevents_a_duplicate_create() -> None:
    existing = {
        "id": "existing-id",
        "email": "primary@example.com",
        "additionalEmails": [{"email": "david@example.com"}],
    }
    client = FakeClient(
        contacts=[{"id": "existing-id"}],
        full_contacts={"existing-id": existing},
        custom_fields=definitions(),
    )

    with pytest.raises(OutputError) as caught:
        driver(client)(
            packet(email="david@example.com"),
            profile(),
            warning=lambda _: None,
        )
    assert 'HighLevel value: "primary@example.com"' in str(caught.value)
    assert 'Incoming TRW value: "david@example.com"' in str(caught.value)
    assert client.creates == [] and client.updates == []


def test_missing_custom_field_aborts_before_contact_search() -> None:
    client = FakeClient(custom_fields=[])
    with pytest.raises(OutputError) as caught:
        driver(client)(
            packet(linkedin_url="https://www.linkedin.com/in/david/"),
            profile(),
            warning=lambda _: None,
        )
    message = str(caught.value)
    assert "does not exist" in message
    assert "Available HighLevel contact custom fields:\n- None" in message
    assert client.creates == []


def test_missing_custom_field_lists_available_names_keys_and_ids() -> None:
    available = [
        {
            "id": "biography-id",
            "name": "Biography",
            "fieldKey": "contact.biography",
        },
        {
            "id": "job-title-id",
            "name": "Job Title",
            "fieldKey": "contact.job_title",
        },
    ]
    client = FakeClient(custom_fields=available)

    with pytest.raises(OutputError) as caught:
        driver(client)(
            packet(linkedin_url="https://www.linkedin.com/in/david/"),
            profile(),
            warning=lambda _: None,
        )

    assert str(caught.value) == (
        "HighLevel custom field 'contact.linkedin_headline' mapped from "
        "'headline' does not exist.\n"
        "Available HighLevel contact custom fields:\n"
        "- Name: Biography\n"
        "  Key: contact.biography\n"
        "  ID: biography-id\n"
        "- Name: Job Title\n"
        "  Key: contact.job_title\n"
        "  ID: job-title-id\n"
        "Update custom_field to an exact name, key, or ID before retrying."
    )
    assert client.creates == []


def test_missing_identity_aborts_before_credentials_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_HIGHLEVEL_LOCATION")
    client = FakeClient(custom_fields=definitions())
    with pytest.raises(OutputError, match="none of the configured.*identity"):
        driver(client)(packet(full_name="David Example"), profile(), warning=lambda _: None)


def test_http_client_identifies_itself_and_uses_v3_json() -> None:
    captured: list[tuple[Any, float]] = []

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        @staticmethod
        def read() -> bytes:
            return b'{"contact":{"id":"created-id"}}'

    def opener(request: Any, *, timeout: float) -> Response:
        captured.append((request, timeout))
        return Response()

    client = HighLevelClient("location-id", "secret-token", opener=opener, timeout=12)
    response = client.create_contact({"locationId": "location-id", "email": "x@example.com"})

    assert response["contact"]["id"] == "created-id"
    request, timeout = captured[0]
    assert timeout == 12
    assert request.full_url == "https://services.leadconnectorhq.com/contacts/"
    assert request.method == "POST"
    assert request.get_header("Version") == "v3"
    assert request.get_header("User-agent").startswith("Transcript-Weaver/")
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert json.loads(request.data) == {
        "locationId": "location-id",
        "email": "x@example.com",
    }


def test_http_error_never_exposes_token_or_response_body() -> None:
    secret = "DO-NOT-PRINT"
    body = json.dumps(
        {
            "message": f"request included {secret} and private@example.com",
            "traceId": "safe-trace-1234",
        }
    ).encode()

    def opener(*args: Any, **kwargs: Any) -> Any:
        raise urllib.error.HTTPError("https://redacted", 403, "forbidden", {}, io.BytesIO(body))

    client = HighLevelClient("location-id", secret, opener=opener)
    with pytest.raises(OutputError) as caught:
        client.list_contacts()
    message = str(caught.value)
    assert "HTTP status 403" in message
    assert "safe-trace-1234" in message
    assert secret not in message
    assert "private@example.com" not in message
