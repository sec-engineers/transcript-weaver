# Releasing Transcript Weaver

Use this checklist only after the intended release candidate has
stopped changing. Publishing, tagging, pushing, and creating a GitHub
release are separate external actions and require explicit
authorization.

## 1. Confirm the source state

- Start from a clean checkout of the exact commit to release.
- Confirm `src/transcript_weaver/_version.py` differs from the preceding
  release by the intended single build increment.
- Confirm `CHANGELOG.md` describes that version and its release date.
- Confirm no configuration, credential, transcript, prompt, log, browser
  artifact, generated journal, or other private file is tracked.
- Confirm GitHub Private Vulnerability Reporting is enabled for the
  repository and that the link in `SECURITY.md` opens the private report
  form.

Run:

```bash
git status --short --branch
git diff --check
```

## 2. Run offline quality gates

```bash
pytest -m 'not live_otter and not live_gemini and not live_highlevel'
ruff check .
ruff format --check .
mypy
```

Push the candidate commit only after these checks pass. Wait for the
complete GitHub Actions matrix to pass on Linux, Windows, and macOS
before proceeding.

## 3. Run authorized live checks

Live checks use credentials, browsers, or external services and remain
opt-in. Run the checks relevant to the changed release behavior:

```bash
TRANSCRIPT_WEAVER_LIVE_GEMINI=1 \
  pytest --no-cov -m live_gemini tests/test_live_gemini.py

TRANSCRIPT_WEAVER_LIVE_OTTER=1 \
  pytest --no-cov -m live_otter tests/test_live_otter.py

TRANSCRIPT_WEAVER_LIVE_HIGHLEVEL=1 \
  pytest --no-cov -m live_highlevel \
  plugins/highlevel/tests/test_live_highlevel.py
```

The HighLevel test creates and deletes only its marked synthetic
contacts. Review its cleanup result before proceeding.

## 4. Build and inspect distributions

Use a clean checkout with no artifacts from earlier versions in `dist/`.
Building never changes the recorded TRW version.

```bash
python -m transcript_weaver.build
```

The build must produce matching core and HighLevel wheel and source
distributions. Python packaging removes leading zeroes from numeric
version components in distribution filenames. Derive that package
version and inspect only the four current artifacts:

```bash
TRW_PACKAGE_VERSION=$(python -c \
  'from transcript_weaver import __version__; print(".".join(str(int(part)) for part in __version__.split(".")))')

python -m twine check \
  "dist/transcript_weaver-${TRW_PACKAGE_VERSION}-py3-none-any.whl" \
  "dist/transcript_weaver-${TRW_PACKAGE_VERSION}.tar.gz" \
  "dist/transcript_weaver_highlevel-${TRW_PACKAGE_VERSION}-py3-none-any.whl" \
  "dist/transcript_weaver_highlevel-${TRW_PACKAGE_VERSION}.tar.gz"
```

Do not use an unrestricted `dist/*` upload from a directory that might
contain artifacts for older versions.

## 5. Test a clean local installation

Install both wheels into a new disposable environment. Do not reuse the
development environment.

```bash
TRW_RELEASE_VENV=$(mktemp -d)
TRW_RELEASE_DATA=$(mktemp -d)

python3 -m venv "$TRW_RELEASE_VENV"
"$TRW_RELEASE_VENV/bin/python" -m pip install \
  "dist/transcript_weaver-${TRW_PACKAGE_VERSION}-py3-none-any.whl" \
  "dist/transcript_weaver_highlevel-${TRW_PACKAGE_VERSION}-py3-none-any.whl"

"$TRW_RELEASE_VENV/bin/trwinp" --version
"$TRW_RELEASE_VENV/bin/trwprep" --version
"$TRW_RELEASE_VENV/bin/trweave" --version
"$TRW_RELEASE_VENV/bin/trwout" --version

printf 'release smoke test\n' | env \
  XDG_CONFIG_HOME="$TRW_RELEASE_DATA/config" \
  XDG_STATE_HOME="$TRW_RELEASE_DATA/state" \
  "$TRW_RELEASE_VENV/bin/trwinp" stdin \
  > "$TRW_RELEASE_DATA/packet.json"

"$TRW_RELEASE_VENV/bin/python" -m json.tool \
  "$TRW_RELEASE_DATA/packet.json"

"$TRW_RELEASE_VENV/bin/python" -c \
  "from transcript_weaver.out.plugins import _load_driver; print(_load_driver('highlevel').api_version)"
```

The four commands must report the exact application version and current
schema. Plugin API `1` must load without contacting HighLevel.

## 6. Publish deliberately

Create the version tag on the exact commit that passed CI and
verification. Use the four explicit artifact paths from the preceding
steps.

Publish the core distribution first because the HighLevel plugin depends
on it. Publish the identically versioned HighLevel distribution second.
Never print or store a PyPI token in the repository or command history.

After publication:

- Install both packages from PyPI into another clean environment.
- Repeat the version and plugin-loading checks.
- Confirm the PyPI descriptions, project links, license files, and
  artifact hashes.
- Create the GitHub release from the verified tag using the matching
  `CHANGELOG.md` section.
- Confirm the GitHub security-reporting link still works.
