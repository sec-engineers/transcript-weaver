# HighLevel output plugin

HighLevel support is an optional official output plugin. Core Transcript
Weaver remains usable without it and does not install a HighLevel SDK. The
plugin uses HighLevel's REST API directly.

Install the plugin into the same Python environment as TRW:

```bash
python3 -m pip install --user transcript-weaver-highlevel
```

If a HighLevel profile is selected without the plugin, `trwout` stops
with that exact installation command. The core and plugin distributions
are built from this repository with one authoritative TRW version. A
small plugin API version check also rejects incompatible combinations
clearly.

## Configuration

The packaged `davids-highlevel-example` profile demonstrates the complete
shape. It reads facts beneath `weave.linkedin` and resolves the location ID
and private integration token at runtime:

```json
{
  "driver": "highlevel",
  "location_id": "command(pass show highlevel/ddr_locationid)",
  "token": "command(pass show highlevel/ddr_pit)",
  "source_path": "weave.linkedin",
  "identity": ["linkedin_url", "email", "phone"],
  "on_conflict": "review",
  "fields": {
    "full_name": {"target": "name"},
    "headline": {"ignore": true},
    "about": {
      "target": {"custom_field": "contact.about_contact"}
    },
    "location": {"ignore": true},
    "email": {"target": "email"},
    "linkedin_url": {
      "target": {"custom_field": "contact.linkedin"}
    }
  }
}
```

Those custom-field keys match David's current HighLevel test location.
Headline and displayed location remain in the enriched packet but are
explicitly omitted from HighLevel because that location has no corresponding
contact fields.

Credential values use the same explicit `env(...)`, `file(...)`,
`command(...)`, and discouraged `literal(...)` forms as provider API keys.
Secrets are never placed in request errors or normal logs. A HighLevel
sub-account private integration token needs contact read/write and location
custom-field read access.

String targets such as `name`, `firstName`, `lastName`, `email`, and
`phone` name standard HighLevel contact fields. A `custom_field` target
may name an existing custom field by exact ID, display name, or field
key. The plugin does not create custom-field definitions. This avoids
silently imposing a CRM schema on a user's location.

Every field present in the selected packet object must have a rule. Fields
which should not reach HighLevel must be acknowledged explicitly:

```json
"unwanted_field": {"ignore": true}
```

This check catches prompt changes before a partial or surprising contact
write. Missing packet fields remain missing; they never clear HighLevel
values.

## Identity and updates

The first version is deliberately conservative:

- A name is never an identity.
- At least one configured identity must be present.
- The plugin reads the location's contacts and compares email, phone, and
  mapped custom identities exactly after safe normalization.
- If identity values match different contacts, nothing is written.
- A new contact receives the mapped fields which are present.
- An existing empty field may be filled.
- An equal field is left alone.
- A different nonempty field stops the entire update for review by default.
- A stopped conflict prints the existing HighLevel value immediately above
  the incoming TRW value so subtle character differences can be compared.
- Missing input never clears an existing field.

Set `on_conflict` on the profile or an individual field to one of:

- `review`: stop before any write;
- `preserve`: retain the existing nonempty value;
- `replace`: accept the incoming value.

Per-field settings override the profile default. Use `replace` only for
fields where the latest extracted profile should be authoritative.

## Live verification

The normal test suite is offline. The opt-in live test uses the two `pass`
entries shown above, creates only a clearly marked synthetic contact in the
configured test location, verifies create/fill/review/replace behavior,
and deletes only contacts carrying all of its ownership markers. Cleanup
runs both before and after the test. A delete failure stops the test
before more contacts are created and reports the retained contact ID.

```bash
TRANSCRIPT_WEAVER_LIVE_HIGHLEVEL=1 \
  pytest --no-cov -m live_highlevel \
  plugins/highlevel/tests/test_live_highlevel.py
```

If `pass` is unavailable, set
`TRANSCRIPT_WEAVER_HIGHLEVEL_LOCATION_ID` and
`TRANSCRIPT_WEAVER_HIGHLEVEL_TOKEN`; the live test prefers those
environment variables when present. GitHub Actions does not run this test
until protected repository secrets are configured deliberately. The
default CI suite remains offline on Linux, Windows, and macOS.

