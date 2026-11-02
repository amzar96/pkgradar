# AGENTS.md

Agent-facing guide to **pkgradar**: what it is, how data flows through it, and the
rules to follow when changing it.

## What this project is

pkgradar is a **read-only dependency radar for local uv projects**. Point it at a
directory; it walks the tree, finds uv projects (`pyproject.toml`, `uv.lock`,
`.venv`), builds a dependency graph from the lockfile, reconciles it against
`dist-info` metadata from the venv, enriches packages from the configured package
indexes and OSV, and reports:

- dependency topology (who requires whom, depth, direct/transitive)
- outdated releases and semver deltas
- known advisories and fixed-in versions
- constraint conflicts and environment drift
- version skew across projects

It ships **one scanner with three front ends**: a FastAPI + React web UI, a
Textual TUI, and `pkgradar scan` for a one-shot terminal report / JSON export.

The core design rule is: **the lockfile is resolution truth, `dist-info` is
environment truth, and pkgradar must never mutate either.**

## Golden rules

1. **Stay read-only.** Never add code that runs `uv add`, `uv lock`, `uv sync`,
   `pip install`, or anything that writes into a scanned project. The only
   subprocesses pkgradar runs are `uv lock --check` and `uv sync --dry-run`. The
   cache under `~/.cache/pkgradar` is the only place pkgradar writes.
2. **Never execute the project interpreter.** Installed versions come from
   `*.dist-info/METADATA`, not `uv pip list`. A venv interpreter is only trusted
   when `.venv/bin/python` is a symlink resolving outside the project
   (`venvs.safe_python`). Windows venvs copy `python.exe`, so they are untrusted
   by design and the sync plan is skipped.
3. **Keep the loopback trust model.** `serve` binds `127.0.0.1`, validates the
   `Host` header via `TrustedHostMiddleware`, and blocks browser requests whose
   `Sec-Fetch-Site` is not same-origin. Non-loopback binding requires
   `--allow-remote`. There is no authentication.
4. **The Pydantic models are the API contract.** `src/pkgradar/models.py` is
   canonical; `web/src/types.ts` must mirror it exactly. If you add/rename/remove
   a field, update both plus any UI that consumes it.
5. **`webdist` is committed.** Frontend changes are not visible in the Python
   app until `cd web && npm run build` regenerates
   `src/pkgradar/webdist/`. Never hand-edit the hashed assets there.
6. **No test suite or linter is configured.** Validate changes manually with the
   commands below and by running a scan.
7. **Keep every related `.md` in sync.** A code change is not done until the docs
   that describe it are updated in the same change. This includes `README.md`,
   this file (`AGENTS.md`), and any relevant Markdown under `docs/`. If you touch
   commands, flags, architecture, data flow, model/API shape, UI behavior,
   security invariants, or limitations, update the matching prose — stale docs
   are a bug, not a follow-up.
8. **Treat index URLs as trusted server-side configuration.** Never accept an
   index URL from the browser/API, never log or cache credentials, namespace the
   cache per index, and read `[[tool.uv.index]]` from scanned repositories only
   with `--trust-project-indexes`. Reject loopback/link-local/metadata hosts in
   project-declared indexes and keep OSV disabled for private-index packages
   unless the operator opts in.

## Quick commands

```bash
# Install Python deps into the local venv
uv sync

# Run the web UI from this repo (defaults to serve, cwd as root)
uv run pkgradar serve --open
uv run pkgradar serve ~/Documents/code --port 6767 --open

# One-shot CLI report / JSON
uv run pkgradar scan ~/Documents/code
uv run pkgradar scan . --fast --no-enrich --no-advisories --json /tmp/report.json --quiet

# Terminal UI (t toggles light/dark)
uv run pkgradar tui ~/Documents/code

# Private index (Nexus/Artifactory/devpi simple API root)
uv run pkgradar scan ~/Documents/code \
  --index-url https://nexus.example.com/repository/pypi-proxy/simple/

# Web build (required after any web/src change)
cd web && npm install && npm run build
```

Useful flags for `scan` / `tui`:

| Flag | Effect |
| --- | --- |
| `--offline` | Index cache only, no network; OSV is skipped |
| `--no-enrich` | Skip all enrichment (index + OSV); no latest/delta/risk-from-delta |
| `--no-advisories` | Skip OSV |
| `--fast` | `deep=False`: skip `uv lock --check` and `uv sync --dry-run` |
| `--index-url` / `--extra-index-url` | Primary/additional package indexes |
| `--index-api auto\|json\|simple` | Index protocol; `auto` tries JSON then PEP 503 |
| `--trust-project-indexes` | Read `[[tool.uv.index]]` from scanned projects |
| `--index-ca-bundle` | CA bundle for a private index |
| `--index-timeout` / `--index-concurrency` | Network tuning |
| `--osv-include-private` | Allow private package names to reach OSV |

`serve` accepts `root`, `--host`, `--port`, `--open`, `--allow-remote`, and the
index flags (server-side only). `tui` also accepts `--theme dark|light`; the
`PKGRADAR_THEME` environment variable is the no-flag fallback. Running `pkgradar`
with no subcommand is rewritten to `serve`.

## Repo map

```
src/pkgradar/
  __init__.py   package version
  cli.py        argparse entry point: scan / serve / tui
  api.py        FastAPI app, SSE scan stream, static web bundle, trust guards
  scanner.py    orchestration: discover -> parse -> venv -> enrich -> analyze
  discover.py   os.walk root, find projects + venvs, attach workspace locks
  locks.py      parse uv.lock into nodes/edges; wire pyproject root edges
  venvs.py      read dist-info, drift, edge-spec enrichment, sync plan, lock check
  graph.py      GraphBuilder: node/edge dedupe, BFS depth/group, cycles, stats
  analyze.py    constraints/intervals, conflicts, enrichment application, risk, skew
  indexes.py    index config, redaction, project-index trust, cache namespaces
  pypi.py       index client: PyPI JSON + PEP 503/691 simple; disk cache
  osv.py        OSV querybatch + vuln detail cache (~/.cache/pkgradar/osv)
  proc.py       subprocess helper; strips VIRTUAL_ENV/CONDA_PREFIX/PYTHONHOME
  utils.py      name/version/requirement parsing, semver delta, safe filenames
  tui.py        Textual app
  models.py     Pydantic wire models (canonical shape)
  webdist/      committed Vite build output (generated; do not edit)
web/
  src/
    App.tsx         shell, scan bootstrap, hash routing, scan overlay
    api.ts          EventSource client for /api/scan
    store.ts        Zustand app state
    types.ts        mirror of src/pkgradar/models.py
    lib/health.ts   health classification + token-based colours + formatting
    lib/theme.ts    theme resolution, pre-paint apply, alpha helper, reduced motion
    components/     Sidebar, TopBar, Inspector, GraphNode, primitives
    views/          Fleet, Topology (lazy), Packages, Conflicts, Skew
  vite.config.ts    dev proxy /api -> 127.0.0.1:6767; build -> ../src/pkgradar/webdist
docs/               README screenshots
```

## Data flow (scanner.py)

1. **Discover** — `discover.discover(root)` walks up to `MAX_DEPTH = 7`, prunes
   `IGNORE_DIRS` and hidden dirs, records `pyproject.toml`, `uv.lock`, and
   `.venv`/`venv`. Workspace members without their own lock inherit the nearest
   parent lock. Broken venvs become warnings, never exceptions.
2. **Build project** — `_build_project` runs per project in a worker thread:
   - If `uv.lock` exists: `locks.load_lock()` creates nodes/edges from the lock
     and wires root edges from `pyproject.toml` (declared ranges are what the UI
     shows; the lock carries resolved versions). The project itself is removed
     from the package list and becomes the `root` node.
   - If no lock but `pyproject.toml` exists: `_declared_graph()` builds a
     declared-only graph with version `"?"` and `available=False`.
   - If `.venv` exists and is sound: `venvs.scan_venv()` reads
     `*.dist-info/METADATA`; `compute_drift()` attaches installed versions and
     marks nodes `same` / `version` / `missing`; `enrich_edge_specs()` borrows
     missing ranges from installed metadata; `reconcile_drift()` filters
     marker-inapplicable packages.
   - If `deep=True`: `lock_check()` runs `uv lock --check` with
     `UV_PROJECT_ENVIRONMENT` pointed at a temp path outside the project;
     `sync_plan()` runs `uv sync --dry-run` only when `safe_python()` passes.
   - A first `collect_conflicts(project, {}, None)` catches constraint/declared
     problems before enrichment.
3. **Graph finalize** — `GraphBuilder.finalize()` assigns BFS depth, group,
   `direct`, `extras`, `dependents`; orphan lock packages are attached to root
   with `kind="inferred"`; DFS counts cycles; duplicate versions are counted.
4. **Enrich** — if `enrich=True`, build the per-project index plan (project
   indexes first, then global indexes), fetch unique `(index, name)` pairs from
   the primary indexes, then fall back through extra indexes only for names the
   primary could not resolve. Results are applied per project so two projects can
   legitimately enrich the same name from different indexes. The default PyPI
   cache is 24h; other indexes are namespaced by URL hash. If
   `advisories=True and not offline`, query OSV in batches of 400 and lazily
   fetch each vuln detail (7-day cache). Only packages resolved from a public
   index are sent to OSV unless `--osv-include-private` is set.
5. **Analyze** — for every project: `apply_enrichment()` (latest, delta,
   releases behind, license, yanked/deprecated, advisories, fixed-in),
   `collect_conflicts()` again with known release lists, `score_risk()` per
   node, `recompute_stats()`.
6. **Skew + result** — `compute_skew()` only when enrichment ran; the final
   `ScanResult` bundles projects, skew, all conflicts, warnings, and scan stats.

Events emitted to callers/SSE: `progress` (phase/message/done/total), `project`
(one project as JSON as soon as parsed), `enrich` (index progress), `done`
(full result), `error`.

## Core concepts

- **Node id**: `"{normalized_name}@{version}"`; the project root is always `"root"`.
  Names are normalized with `utils.normalize_name` (PEP 503: lowercase, runs of
  `-_.` → `-`).
- **Edge kinds**: `runtime`, `dev`, `optional`, `inferred` (orphan attached to
  root). Edges may carry the parent's declared `spec`, `group`, `extra`, `marker`.
- **Depth / group / direct**: computed by BFS from root. Direct means an edge
  from `root`. Orphans get depth 1 and group `main`.
- **Drift**: `same` (installed == locked), `version`, `missing` (locked, not
  installed), plus project-level `venv_only` (installed, not locked) and
  `version_mismatch` rows. `Drift.plan` carries `uv sync --dry-run` output.
- **Delta**: `major`, `minor`, `patch`, `other`, `none`, `unknown` from
  `utils.classify_delta`; `0.x` minor bumps are flagged breaking.
- **Risk**: 0–1 score from delta weight, advisory severity, yanked, deprecated,
  and drift factors (`analyze.score_risk`, weights at top of `analyze.py`).
- **Conflict kinds** (`models.Conflict`):
  - `constraint` — two parent ranges have an empty intersection
  - `declared` — resolved version is outside a parent's declared range (stale lock)
  - `drift` — lock/venv mismatch summary
  - `env` / `resolver` — models exist and analyzers exist, but the current scan
    never populates `venv.check_output` (no `uv pip check`) and passes
    `resolver_raw=None`, so these are effectively dormant paths.
- **Indexes**: `IndexConfig` (in `indexes.py`) holds a credential-free URL plus
  optional username/password. Sources are `default` (PyPI), `cli`, `env`, and
  `project`. Project indexes are opt-in and SSRF-filtered. `IndexRef` is the
  redacted wire shape; `PackageNode.index` is the short name of the index that
  answered. Priority is first-index-wins; a project's local primary wins over the
  global primary for that project.
- **Index cache**: default PyPI keeps `~/.cache/pkgradar/pypi/<name>.json`;
  every other index uses `~/.cache/pkgradar/indexes/<sha256(url)[:16]>/<name>.json`.
  Credentials are never part of the cache key or payload.
- **OSV privacy**: only packages resolved from a public index are sent to OSV by
  default; `--osv-include-private` overrides this.
- **Skew**: one row per package name seen at 2+ distinct versions across
  projects; `versions` maps `project_id -> comma-joined versions`.
- **TUI caps**: topology tree capped at 2,000 nodes and depth 10; `t` toggles
  Textual's `textual-dark`/`textual-light` themes.
- **Discovery caps**: depth 7; hidden directories, `node_modules`, `dist`,
  `build`, `target`, `site-packages`, caches, etc. are pruned.

## HTTP API (`api.py`)

| Method / path | Purpose |
| --- | --- |
| `GET /api/health` | `{ok, version, root}` |
| `GET /api/defaults` | `{root, cwd, version, has_web, indexes, trust_project_indexes}` used by the SPA bootstrap |
| `GET /api/scan` | SSE stream; query: `root`, `offline`, `enrich`, `advisories`, `deep` |
| `GET /api/scan/result` | Same scan as plain JSON (non-streaming) |
| `GET /api/docs` | FastAPI OpenAPI docs |
| `GET /` | Static `webdist` bundle, or a JSON placeholder if not built |

SSE frame names: `progress`, `project`, `enrich`, `done` (payload `{result}`),
`error` (payload `{message}`). The frontend closes the `EventSource` on `done`.

## Web UI

- Hash-routed views: `#fleet`, `#topology`, `#packages`, `#conflicts`, `#skew`.
- `store.ts` (Zustand) owns view, theme, scan status/progress, projects/result,
  scan root, selection, search, layout, depth, group, filters, offline/deep.
- `api.startScan()` wraps `EventSource("/api/scan?...")`; `App.tsx` boots from
  `/api/defaults` and persists the last root in `localStorage` under
  `pkgradar:root`; the theme lives under `pkgradar:theme`.
- The theme is applied pre-paint by an inline script in `web/index.html`, then by
  `lib/theme.ts`. `index.css` defines light values on `:root` and dark values on
  `[data-theme="dark"]`; Tailwind sees them through `@theme inline`. Never add a
  raw hex colour to a component — use the tokens (and `alpha()` from
  `lib/theme.ts` for translucent inline styles).
- Topology is lazy-loaded (`React.lazy` in `App.tsx`) so React Flow + ELK do not
  enter the initial bundle. ELK runs in a Vite web worker; above 300 visible
  nodes the view falls back to the cheap compact grid. Layouts: `auto` (radial at
  ≤26 visible nodes, otherwise compact grid), `radial`, `compact`, `layered`.
  Default depth limit is 1; `99` means all.
- Motion uses short colour/opacity transitions and honours
  `prefers-reduced-motion`; avoid broad `transition-all`, large `backdrop-blur`
  surfaces, or per-node layout work on every keystroke.
- Health colours/labels live in `lib/health.ts` and resolve to CSS tokens.
- Build pipeline: `npm run build` = `tsc --noEmit && vite build`, output to
  `src/pkgradar/webdist` with `emptyOutDir: true`. `Topology` and the ELK worker
  are separate chunks.

## Changing things: recipes

**Add a model field**
1. Add it to `src/pkgradar/models.py` with a safe default.
2. Mirror it in `web/src/types.ts`.
3. Populate it in the right stage (`locks.py`, `venvs.py`, `scanner.py`, or
   `analyze.py`).
4. Render it in the relevant view / Inspector / TUI.
5. Run a scan and rebuild the web bundle if the UI changed.

**Add or change a conflict**
1. Produce a `Conflict` in `analyze.py` (`constraint_conflicts`,
   `env_conflicts`, `drift_conflict`, etc.) with a stable unique `id`.
2. Add the `kind` to the `Literal` in `models.Conflict` and `web/src/types.ts`.
3. Add it to `collect_conflicts()`; dedupe is by `id`.
4. Surface it in `views/Conflicts.tsx` / `tui.py` if it needs special styling.

**Add a web view**
1. Create `web/src/views/YourView.tsx`.
2. Add the id to `View` in `types.ts`, `HASH_VIEWS` in `store.ts`, `NAV` in
   `Sidebar.tsx`, and the `App.tsx` switch.
3. Add any new state to `store.ts`; use selectors rather than whole-state
   subscriptions.
4. `cd web && npm run build` to refresh `webdist`.

**Add a CLI flag**
1. Add it to `_add_scan_flags()` or the relevant subparser in `cli.py`
   (`_add_index_flags()` covers scan/tui/serve).
2. Thread it into `scanner.scan(...)` / `run_tui(...)` / `create_app(...)`.
3. Keep `scan`, `tui`, `serve`, and the API query params consistent when the flag
   maps to a scanner option. Index URLs stay server-side; never add them to
   `/api/scan`.

**Add or change an index source**
1. Extend `indexes.py` (`resolve_indexes`, `project_indexes`,
   `plan_for_project`) and keep the precedence documented.
2. Update `IndexClient` in `pypi.py` for the protocol/auth/cache behavior.
3. Thread the new config through `scanner.scan` and `api.create_app`; include a
   redacted `IndexRef` in `ScanResult.indexes`.
4. Update the TopBar index chip / Inspector provenance and the TUI status line.
5. Add a redaction test (URL userinfo + query token) and a private-index OSV
   skip check to the manual validation pass.

**Change scan performance/network behavior**
- Respect `offline`, `enrich`, `advisories`, `deep` end-to-end.
- Keep disk caches under `~/.cache/pkgradar` and validate cache filenames with
  `utils.safe_filename`.
- Never let a failed network call fail the whole scan; return `available=False`
  or skip the enrichment.

## Documentation sync map

When you change code, update the docs that describe it. At minimum:

| Change | Update |
| --- | --- |
| CLI command, flag, default, or output | `README.md` Quick start / Flags; this file's Quick commands |
| Scanner pipeline, module responsibility, or data flow | `README.md` How it works; this file's Repo map / Data flow |
| Pydantic model, API endpoint, SSE event, or JSON shape | `README.md` HTTP API; this file's Core concepts / HTTP API; mirror `web/src/types.ts` |
| Web view, route, build step, or dev workflow | `README.md` Web UI / Development; this file's Web UI |
| Theme token, palette, motion, or bundle split | `README.md` Web UI; this file's Web UI / Golden rules |
| Package index, auth, protocol, cache, or OSV privacy | `README.md` Private package indexes / Limitations; this file's Golden rules / Data flow / Core concepts |
| TUI keybinding, tab, theme, or cap | `README.md` Terminal UI; this file's TUI caps |
| Security/read-only behavior or trust model | `README.md` Read-only by design / Localhost trust model; this file's Golden rules |
| Known limitation, dormant path, or platform caveat | `README.md` Limitations; this file's Known gotchas |
| Version bump or install instructions | `README.md` Quick start / Requirements; this file's Quick commands |

If a doc statement becomes false, fix or remove it in the same change. Do not
leave a "TODO: update docs" behind.

## Validation checklist

There are no automated tests. Before calling a change done:

```bash
# Python imports / CLI wiring
uv run pkgradar --version
uv run pkgradar --help

# Fast, offline-ish smoke scan (no index/OSV/uv subprocesses)
uv run pkgradar scan . --fast --no-enrich --no-advisories --quiet >/tmp/pkgradar.json
python3 -c "import json;d=json.load(open('/tmp/pkgradar.json'));print(d['stats'])"

# Full-ish scan if network is acceptable
uv run pkgradar scan . --offline

# Index wiring: serve a tiny PEP 503 fixture and scan through it
# (the fixture only needs /simple/<name>/index.html with wheel/sdist links)
uv run pkgradar scan . --index-url http://127.0.0.1:8899/simple/ \
  --index-api simple --fast --no-advisories --quiet

# Web typecheck + production build (also refreshes committed webdist)
cd web && npm run build
```

Manual checks worth doing for UI/scanner changes:

- Docs: re-read the README / AGENTS.md sections touched by the change and confirm
  commands, flags, paths, and behaviour still match the code.
- `uv run pkgradar serve --open` → Fleet loads, rescan works, root chip edits the
  scan root, light/dark toggle persists, topology layouts/filters render, and
  the index chip matches `ScanResult.indexes`.
- TUI: `uv run pkgradar tui .`, switch tabs with `1`–`4`, `t` toggles light/dark,
  `r` rescans, `q` quits.
- Index redaction: configure a URL with `user:pass@host` and a query token; the
  JSON, warnings, UI, and cache path must not contain either secret.
- Private-index privacy: scan with a local/private index and OSV enabled; OSV
  should be skipped unless `--osv-include-private` is passed.
- Project indexes: without `--trust-project-indexes` a `[[tool.uv.index]]` entry
  must produce a warning and be ignored; a loopback project index must be
  rejected even with the flag.
- Scan a directory containing at least one project **without** a lock and one
  with a broken venv; warnings should appear, not crashes.
- If you touched drift logic, compare a project whose venv intentionally differs
  from its lock.

## Known gotchas

- `env_conflicts()` and `resolver_conflict()` exist but are not currently fed
  data (see above). Do not assume "0 env conflicts" means the env is healthy.
- `compute_drift()` keys lock nodes by package **name**, so duplicate versions of
  the same name in one lock may be under-reported.
- `--offline` serves any cached index entry regardless of TTL; missing entries
  become `available=False`. OSV is skipped entirely offline.
- Simple-only indexes (plain Nexus) have no upload time, licence, summary, or
  development-status metadata. Do not invent values; leave them `None`/“—” and
  keep the limitation documented.
- Project-declared indexes are untrusted. `validate_untrusted_index()` blocks
  loopback/link-local/metadata hosts, but DNS rebinding is only mitigated by the
  opt-in flag; do not auto-enable `--trust-project-indexes`.
- Index credentials live only in memory and must be stripped before URLs reach
  logs, `ScanResult`, cache keys, or the UI. `redact_url()` drops userinfo and
  query values.
- The index client caps responses at 32 MiB because PyPI JSON for packages like
  `pydantic-core` is >10 MiB. Do not lower it without checking real payloads.
- `--index-api auto` only tries the legacy JSON API for public indexes; private
  indexes go straight to PEP 503 unless `--index-api json` is explicit.
- First-index-wins is intentional (dependency-confusion mitigation); a package
  found on the primary is not looked up on extras, and a hard primary error
  (auth/TLS/timeout) must not fall through to a public extra index.
- `explicit` project indexes are ignored with a warning because pkgradar does not
  resolve `[tool.uv.sources]`; do not silently apply them to every package.
- Markers are evaluated against the running interpreter environment, overridden
  with the venv's Python version from `pyvenv.cfg` when available. Mutually
  exclusive marker branches are intentionally not cross-checked.
- `uv lock --check` redirects `UV_PROJECT_ENVIRONMENT` to a throwaway path so a
  malicious cloned venv is never used. Do not remove that.
- `serve` has no auth. Keep the loopback default and the `Sec-Fetch-Site` guard.
- The compiled `webdist` bundle must be rebuilt and committed for
  `uv tool install .` to ship a working UI.
- `scan_sync()` uses `asyncio.run`, so it must not be called from inside a
  running event loop; use `await scan(...)` in async code.
- Screenshots in `docs/` are referenced by README; do not rename them casually.
