# Release Channels

This repo publishes to **three channels** on the same Artifactory PyPI index. Which one a consumer sees depends entirely on whether they opt in to pre-releases.

| Trigger | Job | Version published | PEP 440 class | Visible to default `uv add` / `pip install`? |
|---|---|---|---|---|
| Merge to `develop` | `publish-rc` | `X.Y.ZrcN` | pre-release (release candidate) | **No** — hidden by default |
| `workflow_dispatch` | `publish-dev-manual` | `X.Y.Z.devN` | pre-release (dev) | **No** — hidden by default |
| Merge to `main` | `publish` | `X.Y.Z` | stable | **Yes** |

PEP 440 pre-release semantics do the work: `rcN` and `.devN` versions are skipped by every standards-compliant resolver unless the caller explicitly opts in. So production environments stay on stable automatically; dev environments can pull the latest pre-release by flipping one knob.

PEP 440 also orders the pre-release classes: **`.devN` < `aN` < `bN` < `rcN` < final**. This matters here: a consumer who opts in to RCs only (e.g. by pinning the latest RC) will never accidentally pick up a `.devN` build, because the resolver ranks dev builds below RCs. That ordering is what lets RCs and dev builds coexist on the same index without one drowning out the other.

## Why three channels

Two distinct jobs got conflated into the old `.devN` channel and didn't fit together:

1. **"Almost-stable" testing.** Downstream consumers (e.g. `strands-base-agent`) want to validate "what's about to ship from `main`" against their real repos. `.devN` is the wrong signal — it ranks at the bottom of the PEP 440 pre-release ladder and is documented as disposable. The right signal is **`rcN`**: a deliberate "next stable" release candidate cut from green `develop`.
2. **One-off experimental builds.** Engineers occasionally want to share a feature-branch build with someone — a teammate, a downstream repo, a customer — without merging to `develop` first. That's an operator escape hatch: deliberate, disposable, never automatic. The right shape is a manual `workflow_dispatch` that takes a single `package` argument and emits **`X.Y.Z.devN`**.

`main` remains untouched. It is still the only place clean `X.Y.Z` ships and the only one that creates a GitHub Release.

## How publishing works

`.github/workflows/release.yml` reacts to three triggers.

### 1. Merge to `develop` → `publish-rc`

- Reads the base version from `pyproject.toml` (e.g. `0.2.1`).
- Refuses to proceed if the base is already a pre-release — that means someone forgot to bump after the last stable release.
- Mutates `pyproject.toml` **in the runner only** (never committed) to `0.2.1rc<github.run_number>`. **No separator** between the base and `rc` — that is the PEP 440 canonical form (`0.2.1rc42`, not `0.2.1.rc42` or `0.2.1-rc42`). `uv` and `pip` normalise variants, but we emit canonical from the workflow.
- Builds and publishes via the shared `publish-pypi-uv` action with `verify-version: true`.
- Each merge produces a unique `rcN` because `run_number` is monotonic across the workflow file.
- Does **not** create a GitHub Release.

### 2. `workflow_dispatch` → `publish-dev-manual`

- Required input: `package` — the single package to publish, by name (e.g. `foundry-agent-core`). The job rejects unknown values with a clear error. There is no `all` option; manual dev builds are deliberate.
- Allowed from any branch — the dispatcher picks the source ref. The whole point is "I want to share my feature branch's build."
- Reads the base version from the chosen package's `pyproject.toml` on that ref. **There is no version-override input** — operators pick the package, not the number.
- Same pre-release guard as `publish-rc`: refuse if the base is already a pre-release.
- Mutates in-runner-only to `<base>.dev<github.run_number>` (PEP 440 canonical, e.g. `0.2.1.dev87`).
- Same Artifactory index, same publish action, `verify-version: true`.
- Does **not** create a GitHub Release.
- `github.run_number` is shared across all triggers of this workflow file, so an `rcN` at run 42 and a manual `.devN` at run 43 cannot collide on the version number.

### 3. Merge to `main` → `publish`

- Uses the unmutated `pyproject.toml` (e.g. `0.2.1`).
- Same publish action, same Artifactory.
- Creates a GitHub Release. RC and dev jobs do not.

The `pyproject.toml` on `develop` always tracks the **next stable** version. RC and manual-dev publishes derive from it; they never persist back.

## Consumer side (downstream uv projects)

**To stay on stable (the default):** do nothing. `uv add foundry-agent-core` resolves to the latest `X.Y.Z` and ignores all pre-releases.

**To pick up a pre-release, choose one mechanism:**

- **Pin the exact version** (most explicit, recommended for short-lived testing):
  ```bash
  uv add 'foundry-agent-core==0.2.1rc42'
  # or for a manual dev build:
  uv add 'foundry-agent-core==0.2.1.dev87'
  ```
- **Allow pre-releases for that one dependency** (requires `uv` ≥ 0.12.1):
  ```toml
  [tool.uv]
  prerelease-package = { "foundry-agent-core" = "allow" }
  ```
  > ⚠️ Package-scoped `prerelease-package` opts in to **both RCs and dev builds**
  > for that package. If you want RCs only, don't use it — pin the exact RC
  > version (`==0.2.1rc42`). PEP 440's ordering protects you from dev builds
  > *winning* against an RC, but this setting still surfaces dev builds as
  > candidates.
- **Allow pre-releases globally for the consumer project** (broadest, only do this in a dev-only project):
  ```toml
  [tool.uv]
  prerelease = "allow"
  ```

After any of those, run `uv lock --upgrade-package foundry-agent-core` and commit the new `uv.lock`. That lockfile pins what gets installed; nothing magical happens at install time.

**To go back to stable:** remove the pin / setting, run `uv lock --upgrade-package foundry-agent-core`, commit.

## Lifecycle of a single change

The happy path now runs through RCs, not dev builds.

1. Engineer opens a PR to `develop`. CI runs lint/type/tests/dry-run-build.
2. PR merges to `develop`. `publish-rc` publishes `foundry-agent-core==0.2.1rc42` to Artifactory.
3. Downstream consumer pins or allows pre-releases, re-locks, validates the change end-to-end against the RC.
4. When the change is good and ready to ship, a PR is opened from `develop` to `main`.
5. PR to `main` runs `validate` (no publish).
6. PR merges to `main`. `publish` publishes `foundry-agent-core==0.2.1` (the clean version) and creates a GitHub Release.
7. All consumers — including those that were on the RC pin — re-lock and pick up the stable version on their next dependency refresh.

**Manual dev builds are a side note**, not part of the happy path. Use them only when you need an artifact from a feature branch — e.g. to share an in-progress change with a downstream repo before merging to `develop`. Trigger `workflow_dispatch` on the Release workflow, pick the branch, supply the `package` input, and the job publishes `X.Y.Z.devN`.

## Operational rules

- **Bump `pyproject.toml` on `develop` after every stable release.** If `0.2.1` was just published from `main` and the next change merges to `develop` without a bump, `publish-rc` will refuse to publish `0.2.1rcN` (the base is already taken) and the job will fail loudly. The fix is always: bump the version on `develop`.
- **RCs are still pre-releases.** They are cut from green `develop`, but we make no long-term retention promise. If a consumer wants to "stay" on a particular RC for the long haul, that's a signal to wait for the stable release instead.
- **Dev builds are operator-driven and deliberately disposable.** Don't pin them in long-lived branches. If you find yourself needing the same dev build for more than ~a week, that is a signal to push the change to `develop` and let it become an RC.
- **Don't put `[tool.uv] prerelease = "allow"` in production consumer projects.** A pre-release will eventually slip into a release and surprise someone. Keep that setting in dev-only repos, or scope it to one package via `prerelease-package`.
- **Stable releases still come from `main`.** Neither the RC channel nor the manual dev channel turns `develop` (or any other branch) into a release branch — both are side-channels for testing.

## Troubleshooting

**"Why didn't my consumer pick up the RC?"**
You probably forgot the `prerelease = "allow"` opt-in or the explicit pin. By design, `uv add` and `uv sync` ignore `rcN` (and `.devN`) without it. Confirm with `uv pip list | grep foundry-agent-core`.

**"`publish-rc` failed with 'Version 0.2.1rc42 already exists'."**
That RC version was already pushed (likely a re-run of the same workflow). Push another commit to `develop` — the next `run_number` will produce a fresh `rcN`.

**"`publish-rc` failed with 'Base version is already a pre-release'."**
`pyproject.toml` on `develop` is currently `something.devN` or `somethingrcN`. Bump it to a clean stable version (`uv run python scripts/bump_version.py <pkg> patch`) and merge that bump.

**"I ran `workflow_dispatch` but my dev build didn't appear."**
Most common cause: the `package` input didn't match a real package name. The job validates the name against the known list of packages and fails fast with an `::error::` if it doesn't match. Re-run with the exact package directory name (e.g. `foundry-agent-core`, not `foundry_agent_core`).

**"My consumer that opted in to `prerelease = \"allow\"` picked up a dev build instead of the RC."**
That should not happen by version ordering alone — `.devN` ranks below `rcN` in PEP 440, so the resolver prefers the RC. If you saw this, double-check that the RC actually published (look in Artifactory) and that the consumer's lock file isn't pinning the dev build directly.

**"I want to publish from a feature branch."**
Use the manual `workflow_dispatch` job. Pick the branch when dispatching, supply the `package` name, and the workflow will publish `X.Y.Z.devN` from that ref. Do not push to `develop` just to get a build out — that pollutes the RC channel with work that wasn't intended to be the next stable.
