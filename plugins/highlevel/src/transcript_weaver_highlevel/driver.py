"""Conservative HighLevel contact creation and update driver."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from transcript_weaver import __version__
from transcript_weaver.credentials import CredentialError, resolve_credential
from transcript_weaver.out.core import OutputError
from transcript_weaver.out.plugins import OUTPUT_DRIVER_API_VERSION, OutputResult
from transcript_weaver.profiles import extract_dotted

BASE_URL = "https://services.leadconnectorhq.com"
CONTACT_VERSION = "v3"
CUSTOM_FIELD_VERSION = "2023-02-21"
STANDARD_FIELDS = {
    "name",
    "firstName",
    "lastName",
    "email",
    "phone",
    "address1",
    "city",
    "state",
    "postalCode",
    "website",
    "timezone",
    "country",
    "companyName",
}
CONFLICT_POLICIES = {"review", "preserve", "replace"}


@dataclass(frozen=True, slots=True)
class CustomTarget:
    reference: str


@dataclass(frozen=True, slots=True)
class FieldRule:
    target: str | CustomTarget | None
    conflict: str


@dataclass(frozen=True, slots=True)
class DriverConfig:
    location_id: str
    token: str
    source_path: str
    identities: tuple[str, ...]
    fields: dict[str, FieldRule]


@dataclass(frozen=True, slots=True)
class CustomField:
    id: str
    name: str
    key: str


@dataclass(frozen=True, slots=True)
class FieldConflict:
    source: str
    highlevel_value: Any
    incoming_value: str


class HighLevelAPI(Protocol):
    def list_custom_fields(self) -> list[Mapping[str, Any]]: ...

    def list_contacts(self) -> list[Mapping[str, Any]]: ...

    def get_contact(self, contact_id: str) -> Mapping[str, Any]: ...

    def create_contact(self, body: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def update_contact(self, contact_id: str, body: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _object(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OutputError(f"{context} must be a JSON object.")
    return value


def _string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutputError(f"{context} must be a nonempty string.")
    return value.strip()


def _parse_config(profile: Mapping[str, Any]) -> DriverConfig:
    required = {"driver", "location_id", "token", "source_path", "identity", "fields"}
    optional = {"on_conflict"}
    missing = sorted(required - set(profile))
    extra = sorted(set(profile) - required - optional)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if extra:
            details.append(f"unrecognized fields: {', '.join(extra)}")
        raise OutputError(f"HighLevel output profile is invalid ({'; '.join(details)}).")
    if str(profile["driver"]).casefold() != "highlevel":
        raise OutputError("HighLevel output profile driver must be 'highlevel'.")
    default_conflict = profile.get("on_conflict", "review")
    if not isinstance(default_conflict, str) or default_conflict not in CONFLICT_POLICIES:
        raise OutputError("HighLevel on_conflict must be review, preserve, or replace.")
    identity_value = profile["identity"]
    if (
        not isinstance(identity_value, list)
        or not identity_value
        or any(not isinstance(item, str) or not item.strip() for item in identity_value)
    ):
        raise OutputError("HighLevel identity must be a nonempty array of field names.")
    identities = tuple(item.strip() for item in identity_value)
    if len({item.casefold() for item in identities}) != len(identities):
        raise OutputError("HighLevel identity field names must be unique.")
    raw_fields = _object(profile["fields"], context="HighLevel fields")
    if not raw_fields:
        raise OutputError("HighLevel fields must not be empty.")
    fields: dict[str, FieldRule] = {}
    for source_name, raw_rule in raw_fields.items():
        source = _string(source_name, context="HighLevel source field name")
        rule = _object(raw_rule, context=f"HighLevel field {source!r}")
        if rule.get("ignore") is True:
            if set(rule) != {"ignore"}:
                raise OutputError(
                    f"Ignored HighLevel field {source!r} may contain only ignore: true."
                )
            fields[source] = FieldRule(None, "preserve")
            continue
        if "target" not in rule or set(rule) - {"target", "on_conflict"}:
            raise OutputError(
                f"HighLevel field {source!r} must define target, with optional on_conflict."
            )
        conflict = rule.get("on_conflict", default_conflict)
        if not isinstance(conflict, str) or conflict not in CONFLICT_POLICIES:
            raise OutputError(
                f"HighLevel field {source!r} on_conflict must be review, preserve, or replace."
            )
        raw_target = rule["target"]
        if isinstance(raw_target, str):
            target_name = _string(raw_target, context=f"HighLevel field {source!r} target")
            if target_name not in STANDARD_FIELDS:
                raise OutputError(
                    f"HighLevel field {source!r} names unsupported standard target {target_name!r}."
                )
            target: str | CustomTarget = target_name
        else:
            target_object = _object(raw_target, context=f"HighLevel field {source!r} custom target")
            if set(target_object) != {"custom_field"}:
                raise OutputError(
                    f"HighLevel field {source!r} custom target must contain custom_field."
                )
            target = CustomTarget(
                _string(
                    target_object["custom_field"],
                    context=f"HighLevel field {source!r} custom_field",
                )
            )
        fields[source] = FieldRule(target, str(conflict))
    destinations: dict[tuple[str, str], tuple[str, str]] = {}
    for source, parsed_rule in fields.items():
        if parsed_rule.target is None:
            continue
        kind = "standard" if isinstance(parsed_rule.target, str) else "custom"
        reference = (
            parsed_rule.target
            if isinstance(parsed_rule.target, str)
            else parsed_rule.target.reference
        )
        destination = (kind, reference.casefold())
        prior = destinations.get(destination)
        if prior is not None:
            raise OutputError(
                f"HighLevel fields {prior[0]!r} and {source!r} map to the same "
                f"destination {prior[1]!r}. Every non-ignored source field must "
                "have a unique destination."
            )
        destinations[destination] = (source, reference)
    unknown_identities = sorted(set(identities) - set(fields))
    ignored_identities = sorted(name for name in identities if fields[name].target is None)
    if unknown_identities or ignored_identities:
        names = unknown_identities + ignored_identities
        raise OutputError("HighLevel identity fields must have mappings: " + ", ".join(names) + ".")
    return DriverConfig(
        location_id=_string(profile["location_id"], context="HighLevel location_id"),
        token=_string(profile["token"], context="HighLevel token"),
        source_path=_string(profile["source_path"], context="HighLevel source_path"),
        identities=identities,
        fields=fields,
    )


def _trace_id(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    trace = value.get("traceId") or value.get("trace_id")
    return trace if isinstance(trace, str) and re.fullmatch(r"[A-Za-z0-9-]{4,100}", trace) else None


class HighLevelClient:
    def __init__(
        self,
        location_id: str,
        token: str,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout: float = 30,
    ) -> None:
        self.location_id = location_id
        self._token = token
        self._opener = opener
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        version: str,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        url = BASE_URL + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": f"Transcript-Weaver/{__version__}",
            "Version": version,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                error_body = json.loads(exc.read(65_536).decode("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                error_body = None
            trace = _trace_id(error_body)
            suffix = f" (trace ID {trace})" if trace else ""
            if exc.code in {401, 403}:
                suffix += "; verify the token and required HighLevel scopes"
            raise OutputError(
                f"HighLevel request failed with HTTP status {exc.code}{suffix}."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise OutputError(
                "HighLevel request failed because the service was unreachable."
            ) from None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise OutputError("HighLevel returned an invalid JSON response.") from None
        if not isinstance(value, Mapping):
            raise OutputError("HighLevel returned an unexpected response shape.")
        return value

    def list_custom_fields(self) -> list[Mapping[str, Any]]:
        result = self._request(
            "GET",
            f"/locations/{urllib.parse.quote(self.location_id, safe='')}/customFields",
            version=CUSTOM_FIELD_VERSION,
            query={"model": "contact"},
        )
        fields = result.get("customFields")
        if not isinstance(fields, list) or any(not isinstance(item, Mapping) for item in fields):
            raise OutputError("HighLevel custom-field response is malformed.")
        return fields

    def list_contacts(self) -> list[Mapping[str, Any]]:
        contacts: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        page = 1
        while True:
            result = self._request(
                "POST",
                "/contacts/search",
                version=CONTACT_VERSION,
                body={"locationId": self.location_id, "page": page, "pageLimit": 100},
            )
            batch = result.get("contacts")
            if not isinstance(batch, list) or any(not isinstance(item, Mapping) for item in batch):
                raise OutputError("HighLevel contact-search response is malformed.")
            for contact in batch:
                contact_id = contact.get("id")
                if not isinstance(contact_id, str) or not contact_id:
                    raise OutputError("HighLevel contact-search response contains no contact ID.")
                if contact_id in seen:
                    raise OutputError(
                        "HighLevel contact pagination repeated a contact unexpectedly."
                    )
                seen.add(contact_id)
                contacts.append(contact)
            total = result.get("total")
            if not batch or len(batch) < 100:
                break
            if isinstance(total, int) and len(contacts) >= total:
                break
            page += 1
            if page > 10_000:
                raise OutputError("HighLevel contact pagination exceeded its safety limit.")
        return contacts

    def get_contact(self, contact_id: str) -> Mapping[str, Any]:
        result = self._request(
            "GET",
            f"/contacts/{urllib.parse.quote(contact_id, safe='')}",
            version=CONTACT_VERSION,
        )
        return _object(result.get("contact"), context="HighLevel contact response")

    def create_contact(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._request("POST", "/contacts/", version=CONTACT_VERSION, body=body)

    def update_contact(self, contact_id: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._request(
            "PUT",
            f"/contacts/{urllib.parse.quote(contact_id, safe='')}",
            version=CONTACT_VERSION,
            body=body,
        )

    def delete_contact(self, contact_id: str) -> Mapping[str, Any]:
        return self._request(
            "DELETE",
            f"/contacts/{urllib.parse.quote(contact_id, safe='')}",
            version=CONTACT_VERSION,
        )


def _custom_definitions(raw_fields: list[Mapping[str, Any]]) -> list[CustomField]:
    definitions: list[CustomField] = []
    for raw in raw_fields:
        field_id = raw.get("id")
        name = raw.get("name")
        key = raw.get("fieldKey")
        if not all(isinstance(value, str) and value for value in (field_id, name, key)):
            raise OutputError("HighLevel returned an invalid custom-field definition.")
        definitions.append(CustomField(str(field_id), str(name), str(key)))
    return definitions


def _resolve_custom_fields(
    rules: Mapping[str, FieldRule], definitions: list[CustomField]
) -> dict[str, CustomField]:
    resolved: dict[str, CustomField] = {}
    for source, rule in rules.items():
        if not isinstance(rule.target, CustomTarget):
            continue
        reference = rule.target.reference.casefold()
        matches = [
            field
            for field in definitions
            if reference in {field.id.casefold(), field.name.casefold(), field.key.casefold()}
        ]
        if not matches:
            available = ["Available HighLevel contact custom fields:"]
            if definitions:
                for field in sorted(definitions, key=lambda item: item.name.casefold()):
                    available.extend(
                        (
                            f"- Name: {field.name}",
                            f"  Key: {field.key}",
                            f"  ID: {field.id}",
                        )
                    )
            else:
                available.append("- None")
            raise OutputError(
                f"HighLevel custom field {rule.target.reference!r} mapped from "
                f"{source!r} does not exist.\n"
                + "\n".join(available)
                + "\nUpdate custom_field to an exact name, key, or ID before retrying."
            )
        if len(matches) != 1:
            raise OutputError(
                f"HighLevel custom field reference {rule.target.reference!r} is ambiguous."
            )
        resolved[source] = matches[0]
    resolved_destinations: dict[str, tuple[str, CustomField]] = {}
    for source, field in resolved.items():
        prior = resolved_destinations.get(field.id.casefold())
        if prior is not None:
            raise OutputError(
                f"HighLevel fields {prior[0]!r} and {source!r} resolve to the "
                f"same custom field {field.name!r} ({field.key}). Every "
                "non-ignored source field must have a unique destination."
            )
        resolved_destinations[field.id.casefold()] = (source, field)
    return resolved


def _custom_values(contact: Mapping[str, Any]) -> dict[str, Any]:
    raw_values = contact.get("customFields", [])
    if raw_values is None:
        return {}
    if not isinstance(raw_values, list):
        raise OutputError("HighLevel contact customFields is malformed.")
    values: dict[str, Any] = {}
    for raw in raw_values:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str):
            raise OutputError("HighLevel contact customFields is malformed.")
        value = raw.get("fieldValue", raw.get("value"))
        values[str(raw["id"])] = value
    return values


def _current_value(
    contact: Mapping[str, Any],
    source: str,
    rule: FieldRule,
    custom: Mapping[str, CustomField],
) -> Any:
    if isinstance(rule.target, str):
        return contact.get(rule.target)
    if isinstance(rule.target, CustomTarget):
        return _custom_values(contact).get(custom[source].id)
    return None


def _normalized(source: str, target: str | CustomTarget | None, value: str) -> str:
    cleaned = value.strip()
    if target == "email":
        return cleaned.casefold()
    if target == "phone":
        return re.sub(r"\D", "", cleaned)
    if source.casefold() == "linkedin_url":
        parsed = urllib.parse.urlsplit(cleaned)
        host = parsed.netloc.casefold()
        if host.startswith("www."):
            host = host[4:]
        path = "/" + parsed.path.strip("/").casefold()
        return urllib.parse.urlunsplit(("https", host, path, "", ""))
    return cleaned


def _same(source: str, rule: FieldRule, incoming: str, existing: Any) -> bool:
    if not isinstance(existing, str):
        return False
    return _normalized(source, rule.target, incoming) == _normalized(source, rule.target, existing)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _contact_id(contact: Mapping[str, Any]) -> str:
    return _string(contact.get("id"), context="HighLevel contact ID")


def _identity_values(
    contact: Mapping[str, Any],
    source: str,
    rule: FieldRule,
    custom: Mapping[str, CustomField],
) -> list[Any]:
    values = [_current_value(contact, source, rule, custom)]
    additional_name = "additionalEmails" if rule.target == "email" else None
    item_name = "email"
    if rule.target == "phone":
        additional_name = "additionalPhones"
        item_name = "phone"
    if additional_name is None:
        return values
    additional = contact.get(additional_name, [])
    if additional is None:
        return values
    if not isinstance(additional, list) or any(
        not isinstance(item, Mapping) for item in additional
    ):
        raise OutputError(f"HighLevel contact {additional_name} is malformed.")
    values.extend(item.get(item_name) for item in additional)
    return values


def _find_contact(
    client: HighLevelAPI,
    contacts: list[Mapping[str, Any]],
    source_data: Mapping[str, str],
    config: DriverConfig,
    custom: Mapping[str, CustomField],
) -> Mapping[str, Any] | None:
    matches: dict[str, Mapping[str, Any]] = {}
    for summary in contacts:
        contact_id = _contact_id(summary)
        contact = client.get_contact(contact_id)
        for source in config.identities:
            incoming = source_data.get(source)
            if incoming is None:
                continue
            rule = config.fields[source]
            existing_values = _identity_values(contact, source, rule, custom)
            if any(_same(source, rule, incoming, existing) for existing in existing_values):
                matches[contact_id] = contact
                break
    if len(matches) > 1:
        raise OutputError(
            "HighLevel identity values match multiple contacts; no contact was changed."
        )
    return next(iter(matches.values()), None)


def _mapped_source(packet: Mapping[str, Any], config: DriverConfig) -> dict[str, str]:
    try:
        raw = extract_dotted(packet, config.source_path, field="HighLevel source_path")
    except ValueError as exc:
        raise OutputError(str(exc)) from exc
    source = _object(raw, context=f"Packet field {config.source_path}")
    if any(not isinstance(name, str) for name in source):
        raise OutputError("HighLevel source field names must be strings.")
    unknown = sorted(set(source) - set(config.fields))
    if unknown:
        raise OutputError(
            "HighLevel profile must map or explicitly ignore every incoming field. "
            f"Unmapped fields: {', '.join(str(name) for name in unknown)}."
        )
    result: dict[str, str] = {}
    for name, value in source.items():
        assert isinstance(name, str)
        if not isinstance(value, str) or not value.strip():
            raise OutputError(f"HighLevel source field {name!r} must be a nonempty string.")
        result[name] = value.strip()
    identities = [name for name in config.identities if name in result]
    if not identities:
        raise OutputError(
            "Packet contains none of the configured HighLevel identity fields; "
            "no contact was changed."
        )
    return result


def _write_values(
    source_data: Mapping[str, str],
    config: DriverConfig,
    custom: Mapping[str, CustomField],
    *,
    existing: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[FieldConflict]]:
    standard: dict[str, Any] = {}
    custom_values: list[dict[str, Any]] = []
    conflicts: list[FieldConflict] = []
    for source, incoming in source_data.items():
        rule = config.fields[source]
        if rule.target is None:
            continue
        current = _current_value(existing, source, rule, custom) if existing is not None else None
        should_write = existing is None or _empty(current)
        if existing is not None and not _empty(current):
            if _same(source, rule, incoming, current):
                continue
            if rule.conflict == "review":
                conflicts.append(FieldConflict(source, current, incoming))
                continue
            should_write = rule.conflict == "replace"
        if not should_write:
            continue
        if isinstance(rule.target, str):
            standard[rule.target] = incoming
        else:
            custom_values.append({"id": custom[source].id, "fieldValue": incoming})
    if custom_values:
        standard["customFields"] = custom_values
    return standard, conflicts


def _conflict_message(conflicts: list[FieldConflict]) -> str:
    lines = ["HighLevel contact has different nonempty values:"]
    for conflict in sorted(conflicts, key=lambda item: item.source.casefold()):
        lines.extend(
            (
                f"Field: {conflict.source}",
                "HighLevel value: " + json.dumps(conflict.highlevel_value, ensure_ascii=False),
                "Incoming TRW value: " + json.dumps(conflict.incoming_value, ensure_ascii=False),
            )
        )
    lines.extend(
        (
            "No contact was changed.",
            "Review the values or configure on_conflict as preserve or replace.",
        )
    )
    return "\n".join(lines)


def _response_contact_id(response: Mapping[str, Any]) -> str:
    contact = response.get("contact")
    if not isinstance(contact, Mapping):
        raise OutputError("HighLevel response did not contain the written contact.")
    return _contact_id(contact)


class HighLevelDriver:
    api_version = OUTPUT_DRIVER_API_VERSION

    def __init__(
        self,
        client_factory: Callable[[str, str], HighLevelAPI] = HighLevelClient,
    ) -> None:
        self._client_factory = client_factory

    def __call__(
        self,
        packet: Mapping[str, Any],
        profile: Mapping[str, Any],
        *,
        warning: Callable[[str], None],
    ) -> OutputResult:
        config = _parse_config(profile)
        source_data = _mapped_source(packet, config)
        try:
            location_id = resolve_credential(
                config.location_id, label="HighLevel location ID", warning=warning
            )
            token = resolve_credential(config.token, label="HighLevel token", warning=warning)
        except CredentialError as exc:
            raise OutputError(str(exc)) from None
        client = self._client_factory(location_id, token)
        custom_needed = any(
            isinstance(rule.target, CustomTarget) for rule in config.fields.values()
        )
        definitions = _custom_definitions(client.list_custom_fields()) if custom_needed else []
        custom = _resolve_custom_fields(config.fields, definitions)
        found = _find_contact(client, client.list_contacts(), source_data, config, custom)
        if found is None:
            values, conflicts = _write_values(source_data, config, custom, existing=None)
            if conflicts:  # pragma: no cover - impossible for a new contact
                raise AssertionError(conflicts)
            body = {"locationId": location_id, "source": "Transcript Weaver", **values}
            contact_id = _response_contact_id(client.create_contact(body))
            return OutputResult("created", f"HighLevel contact {contact_id}")
        contact_id = _contact_id(found)
        values, conflicts = _write_values(source_data, config, custom, existing=found)
        if conflicts:
            raise OutputError(_conflict_message(conflicts))
        if not values:
            return OutputResult("unchanged", f"HighLevel contact {contact_id}")
        response = client.update_contact(contact_id, values)
        written_id = _response_contact_id(response)
        if written_id != contact_id:
            raise OutputError("HighLevel updated an unexpected contact ID.")
        return OutputResult("updated", f"HighLevel contact {contact_id}")
