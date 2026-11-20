# Full-stack integration gate

## Release candidate

`release-e2e.yml` accepts a manual release run from `overmindv/infra` on `main`.
Pass the contents of the published `release.json` from infra and the full
`tests_ref` SHA used in the reusable workflow reference. The caller needs
`contents: read`, `packages: read` and access to the candidate GHCR packages.
No cross-repository source token is needed for Feed or Sandbox.

The job checks out only tests and the infra SHA from the manifest. The infra
SHA must be in the history of `main`. The job creates
a new Compose project with credentials from `prepare-env.sh`; a failure does
not fall back to a shared account. It removes build contexts, disables Kafka
UI and publishes frontend and gateway on loopback only. The hosted runner
starts the real go-judge profile. This is a disposable test stack, not a
production isolation check.

`observed-release.json` records the manifest checksum, tests and infra SHAs,
the source SHAs checked against image labels, and the image ID and state of
each container. Compose cannot rebuild any image or pull a tag during startup.
API/browser results and failure diagnostics are published only after the
credential scan, separately from the observed stack. The job never uploads
the generated env file. A stack receipt alone does not mean the journeys passed.

For a local config check with Docker Compose 2.24.4 or newer, use a checkout
of the infra SHA from the manifest and a new run directory:

```sh
python3 scripts/release_stack.py render --manifest /path/to/release.json \
  --infra /path/to/infra --run-dir /tmp/release-ci-0123456789ab
```

This does not pull images or start containers. Do not use a shared Docker host
for the full release job.

## Source-based integration

`.github/workflows/e2e.yml` runs harness/privacy checks on tests pull requests.
The full reusable gate is invoked by the private recommendations repository. It
loads dependencies at the full commits in `source-refs.json`, starts a fresh
Compose project with `sandbox` and `gojudge`, and executes all six API scenarios
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

For direct pytest runs, provide `BOOTSTRAP_SUPERUSER_EMAIL` and
`BOOTSTRAP_SUPERUSER_PASSWORD` from that dedicated stack; there are no defaults.

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


The recommendation API scenario creates an active topic and two linked tasks via
admin GraphQL, then checks the real `practicePlan` through the gateway. It asserts
START_TOPIC initially, PRACTICE_GAP after a stored wrong answer, and exclusion of
the solved task with NEXT_CHALLENGE after acceptance. An unavailable recommendation
service cannot pass this scenario. This is API coverage; the browser journey still
covers author publication and student answers/history, not the `/practice` page.
