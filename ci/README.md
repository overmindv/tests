# Full-stack integration gate

`.github/workflows/e2e.yml` runs harness/privacy checks on tests pull requests.
The full reusable gate is invoked by the private recommendations repository. It
loads dependencies at the full commits in `source-refs.json`, starts a fresh
Compose project with `sandbox` and `gojudge`, and executes all five API scenarios
plus the real student/author browser journey on laptop and phone viewports.
Other per-service e2e callers are not enabled by this change.

Update the manifest when a coordinated service change must be verified. A caller
of the reusable workflow may explicitly override its own service with the caller
SHA; recommendations uses its caller SHA before private-source extraction. All
other checkouts stay pinned. `observed-source-refs.json` in the evidence artifact
records the actual Git HEADs, including tests/caller and the archive checksum. The refs are an input snapshot, not a claim
that every run passed. The Actions result is the evidence for that exact snapshot.

The caller uses its own `GITHUB_TOKEN` for private recommendations; private sandbox
source is verified from its committed snapshot as described below. No personal
access token is installed. The generated infra `.env` supplies bootstrap credentials directly
to the Python runner; passwords are never CLI arguments. Only evidence that passes
the credential/JWT scan is uploaded. Playwright trace, HAR, video, and session
storage remain disabled. Do not upload `.env` or local fixture files.

Local equivalent (after starting a dedicated stack with real gojudge):

```sh
.venv/bin/python scripts/run_e2e.py --infra-env ../infra/.env
# Optional: retain synthetic accounts for local browser review (file mode 600).
.venv/bin/python scripts/run_e2e.py --infra-env /path/to/dedicated/.env \
  --browser-env /path/outside/repo/live-fixtures.env
```

The deterministic programming scenario creates its own task, verifies three public
examples with correct Python DP, and rejects incorrect code. It replaces a test
that assumed a pre-approved external task already existed and accepted either
verdict. Collection coverage remains the request/queued-job contract; external
website parsing, candidate review, and hidden judge cases are not claimed here.

Reporting regression checks: `python -m pytest unit_tests`. The API selector is
`python -m pytest -m 'e2e and not skip_ci'`. Browser scenarios still run if an API
scenario fails, so both student and author evidence is available for diagnosis.

## Расположение полного gate

Recommendations — закрытый репозиторий, deploy keys запрещены организацией. Поэтому
полный reusable e2e вызывается из его workflow с собственным GITHUB_TOKEN. В tests PR
выполняются проверки harness/privacy/выбора тестов; полноценный результат ищется в
recommendations Actions. Caller фиксирует tests_ref и workflow SHA; личные PAT в
CI не добавляются.


## Private sandbox source

The recommendations caller owns an immutable `ci/vendor/sandbox.tar.gz` snapshot
and `sandbox-source.json` manifest in its **private** repository. The archive is
created with `git archive` from the committed sandbox ref; untracked or working
changes are not included. Its manifest records `repository`, full `commit`, and
SHA-256 of the archive bytes. This avoids persisting a broad cross-repository token
or changing sandbox visibility. Never copy this archive into the public tests repo
or upload it as test evidence.

Before building, the tests workflow verifies the repository, requires the manifest
commit to equal `ci/source-refs.json`'s sandbox pin, verifies SHA-256, and extracts
with Python tarfile's `data` safety filter. A missing/mismatched snapshot fails the
build. When sandbox changes, regenerate the archive+manifest in recommendations
and update the pin together. This temporary duplication can be removed when a
scoped cross-repository CI credential is available.
