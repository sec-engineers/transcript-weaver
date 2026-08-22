# Transcript Weaver Agent Guidance

## Scope

These instructions apply to the entire repository.

Preserve the existing architecture, CLI behavior, packet compatibility, and
configuration compatibility unless the user explicitly requests a change.

Do not stage, commit, push, publish, or create releases unless the user
explicitly authorizes that action.

Existing working-tree changes may belong to the user. Preserve unrelated
changes and report them without treating them as errors.

## Version policy

`src/transcript_weaver/_version.py` is the authoritative project version.

TRW uses `major.minor.build`, with a four-digit build component.

When making a persistent, release-relevant change:

1. Compare the working-tree version with the version at `HEAD`.
2. If they are identical, increment the build component exactly once.
3. If the working-tree version already differs from `HEAD`, do not increment
   it again; the pending change set has already been versioned.
4. Add or update the corresponding `CHANGELOG.md` entry.
5. Update exact-version tests and verify CLI version output.

Release-relevant changes include functionality, bug fixes, CLI behavior,
configuration behavior, packet or schema behavior, packaging behavior, and
significant accompanying documentation.

Do not increment the version for investigation, tests, reinstallations,
repeated builds, CI runs, generated files, or personal TODO notes.

Several related edits made before the pending changes are committed share one
build number.

## Builds

Building identical source must not change the project version.

Do not invoke a command that mutates the source version merely to verify a
build. If the existing build tooling conflicts with this policy, report the
conflict rather than silently changing the version.

## Testing

For normal changes, run:

    pytest
    ruff check .
    ruff format --check .
    mypy

The live Gemini and Otter tests are opt-in and may require credentials,
browser state, or external services. Do not run them unless the user requests
live verification or the change specifically requires it.

Add or update focused automated tests for changed behavior.

## Project conventions

Use existing version and schema constants rather than introducing duplicate
hard-coded values.

Preserve argparse's standard behavior unless a CLI change explicitly requires
otherwise.

Output body formats support `{date}`, `{time}`, `{content}`, and dotted packet
paths. `{content}` is the configured, validated, soft-wrapped primary body.
Create-operation filenames support only `{date}` and `{time}`.

Treat personal configuration files, transcripts, prompts, logs, browser
artifacts, credentials, and generated journals as potentially sensitive. Do
not commit or display them unless explicitly requested.
