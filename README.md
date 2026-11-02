# pkgradar

**A dependency radar for local [uv](https://docs.astral.sh/uv/) projects.** Point it at a folder,
and it maps every `uv.lock` + `.venv` underneath: the full dependency graph, what each version is
pinned by, what has drifted from the lock, which packages are outdated or vulnerable, and which
versions disagree across projects.

One scanner, three ways in: a dark, radar-style **web UI**, a **terminal UI**, and a
one-shot **CLI report / JSON export**.

> Working on pkgradar? [AGENTS.md](AGENTS.md) documents the architecture, data flow,
> invariants, and change checklist for coding agents.

![Fleet overview](docs/fleet.png)

## What it answers

| Question | Where |
| --- | --- |
| Why is this package on this version? Who requires it? | Topology → click a node (blame chain, required-by) |
| What's the blast radius of a conflict? | Conflicts → constraint intersections with every parent spec |
| Is my venv actually in sync with `uv.lock`? | Conflicts → environment drift + `uv sync` plan |
| What's outdated, and by how much? | Packages → locked vs latest PyPI release, semver delta, releases behind |
| Which releases have known CVEs? | Topology badges, Packages, Inspector (OSV advisories + fixed version) |
| Which packages disagree across my projects? | Skew → version spread per project |
| What's bloating this venv? | Packages/Projects → duplicates, orphaned installs, depth/weight |

## Screenshots

Radial topology for a focused project (16 direct deps), straight spokes from the project root:

![Radial topology](docs/topology-radial.png)

Compact grid for large fan-outs — `bondeat-api-v2` declares **92 direct dependencies**, so the
layout switches to an aspect-matched wall automatically (`auto`):

![Compact topology](docs/topology-compact.png)

Outdated + advisory triage, worst first:

![Packages](docs/packages.png)

Cross-project version skew (green = newest, yellow = behind, red = oldest and behind):

![Skew](docs/skew.png)

Terminal UI — package tree with an inspector, plus conflicts and skew tabs:

![TUI topology](docs/tui-topology.jpg)
![TUI skew](docs/tui-skew.jpg)

## Requirements

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — required for the optional deep checks
  (`uv lock --check`, `uv sync --dry-run`) and expected for the projects it scans
- **Node.js 20+ and npm** — only needed to build or develop the web UI

pkgradar is read-only: it never installs, syncs, or edits the projects it scans.

## Quick start

```bash
# from this repo, no install
uv run --project . pkgradar serve --open

# or install it as a tool
uv tool install .
pkgradar serve ~/Documents/code --port 6767 --open
```

Then open <http://127.0.0.1:6767>.

```bash
pkgradar                       # alias for `serve` in the current directory
pkgradar scan ~/code           # one-shot rich report in the terminal
pkgradar scan ~/code --json report.json --quiet
pkgradar tui ~/code            # terminal UI
```

Scanning `~/Documents/code` (5 uv projects, 316 package instances) takes ~2s warm and ~14s cold,
mostly PyPI/OSV network time. Results are cached under `~/.cache/pkgradar`.

### Flags

These apply to `scan` and `tui`; `serve` takes `root`, `--host`, `--port`, `--open` and
`--allow-remote`.

| Flag | Effect |
| --- | --- |
| `--offline` | Use cached PyPI data only, no network; OSV is skipped |
| `--no-enrich` | Skip all enrichment (PyPI and OSV) |
| `--no-advisories` | Skip OSV lookups |
| `--fast` | Skip `uv lock --check` and `uv sync --dry-run` |

## Web UI

Hash-routed views, all backed by one `/api/scan` SSE stream:

- **`#fleet`** — every project found under the root, with package, outdated, advisory and drift counts.
- **`#topology`** — React Flow + ELK graph. Layouts: `auto` (radial under ~26 visible nodes, otherwise
  compact grid), `radial`, `compact`, `layered`. Depth selector (`1…all`), group filter, outdated /
  advisory filters, search dimming, path highlight to the selected node, `+N hidden` to expand.
- **`#packages`** — sortable table: locked, latest, semver delta, CVEs, risk, dependents, installed, depth.
- **`#conflicts`** — constraint intersections and lock/venv drift; range conflicts include the blame chain.
- **`#skew`** — one row per package, one column per project.

The graph reads from the **lockfile** (resolution truth) and reconciles against **installed
`dist-info` metadata** (environment truth). When the two disagree, nodes are marked `missing` or
`version`; installed-only packages are reported as project-level drift.

## Terminal UI

```
1 Fleet     2 Topology     3 Conflicts     4 Skew     r Rescan     q Quit
```

- **Fleet** — project table with venv interpreter, lock state, drift.
- **Topology** — collapsible dependency tree per project (capped at 2,000 nodes and depth 10);
  highlighting a package shows latest version, delta, installed version, risk factors, advisories
  (with fixed-in), and every package that requires it.
- **Conflicts / Skew** — the same data as the web tables.

Scanning happens in a background worker, so the UI stays responsive; `r` re-runs it.

## HTTP API

The web UI is a thin client over the scanner; the same data is available directly.

| Method / path | Purpose |
| --- | --- |
| `GET /api/health` | `{ok, version, root}` |
| `GET /api/defaults` | `{root, cwd, version, has_web}` used by the SPA bootstrap |
| `GET /api/scan` | SSE stream; query params `root`, `offline`, `enrich`, `advisories`, `deep` |
| `GET /api/scan/result` | Same scan as a single JSON `ScanResult` |
| `GET /api/docs` | FastAPI/OpenAPI docs |

The SSE stream emits `progress`, `project` (one project as soon as it is parsed),
`enrich`, `done` (the full `ScanResult`), and `error` events. A typical non-streaming
call:

```bash
curl 'http://127.0.0.1:6767/api/scan/result?root=/path/to/code&offline=true'
```

## Read-only by design

pkgradar never mutates your projects. It only runs:

- `uv lock --check` (whether the lock matches `pyproject.toml`)
- `uv sync --dry-run` (planned installs/uninstalls — advisory only, and only when the venv is trusted)
- plain reads of `uv.lock`, `pyproject.toml`, and `.venv/**/dist-info/METADATA`

No `uv add`, `uv lock`, `uv sync`, or `pip install` is ever invoked. The scanner also strips
`VIRTUAL_ENV`, `CONDA_PREFIX` and `PYTHONHOME` from child processes so a scan can't be redirected
into the wrong environment.

### Scanning untrusted code

A cloned repository can ship an executable at `.venv/bin/python`, and `uv` queries that interpreter
even for `lock --check` / `sync --dry-run`. pkgradar therefore:

- runs `uv lock --check` with `UV_PROJECT_ENVIRONMENT` pointed at a throwaway path outside the
  project, so uv never touches the project interpreter;
- never runs `uv pip list` / `uv pip check` (installed versions come from `dist-info`);
- skips `uv sync --dry-run` unless `.venv/bin/python` is a symlink that resolves outside the project
  (the normal POSIX venv layout). Windows venvs copy `python.exe`, so the sync plan is skipped there.

### Localhost trust model

`pkgradar serve` binds `127.0.0.1` and validates the `Host` header, which blocks DNS-rebinding
attacks from web pages. API requests carrying `Sec-Fetch-Site: cross-site` (or `same-site`) are
rejected, so a random website cannot drive-by trigger scans. The server has **no authentication**:
binding a non-loopback interface requires `--allow-remote` and exposes the read-only scanner (and
your local paths/package names) to your network. Put it behind an authenticating proxy if you need
remote access.

## How it works

```
src/pkgradar/
  discover.py   walk a root, find uv projects (pyproject + uv.lock + .venv)
  locks.py      parse uv.lock into nodes/edges; workspace + group handling
  venvs.py      dist-info METADATA, drift + sync plan (no interpreter execution)
  graph.py      BFS depths, orphans, cycles, root edges
  analyze.py    constraint intervals, conflict blame, risk score, cross-project skew
  pypi.py       PyPI JSON (latest, upload date, yanked/deprecated), disk cache
  osv.py        OSV querybatch advisories, per-package
  scanner.py    orchestration; emits progress/project/enrich/done events
  api.py        FastAPI + SSE + static web bundle + loopback guards
  cli.py        scan / serve / tui
  tui.py        Textual app
  models.py     Pydantic models; canonical JSON shape for the API + web types
  proc.py       subprocess helper; strips VIRTUAL_ENV/CONDA_PREFIX/PYTHONHOME
  utils.py      name/version/requirement parsing, semver delta, safe filenames
web/src/        React 19 + Vite + Tailwind v4 + @xyflow/react + elkjs + zustand
```

The scan is a pipeline: **discover → parse lock / declared graph → read venv dist-info and reconcile
drift → enrich from PyPI and OSV → compute conflicts, risk, skew, and stats**. The lockfile is
treated as resolution truth and `dist-info` as environment truth; a stale venv is reported as drift,
not as an unsatisfiable solver result.

Conflict detection computes the **allowed interval per parent specifier** (marker-aware, using
installed metadata when lock edges are ambiguous) and flags packages whose resolved version falls
outside a parent's constraint. Lock/venv drift is reconciled separately from solver errors, so a
stale venv doesn't masquerade as an unsatisfiable dependency set. Deep scans additionally run
`uv lock --check` and, when the venv interpreter is trustworthy, `uv sync --dry-run` to report the
exact install/uninstall plan.

The Pydantic models in `src/pkgradar/models.py` are the wire contract; `web/src/types.ts` mirrors
them. See [AGENTS.md](AGENTS.md) for the module-by-module data flow and change recipes.

## Development

```bash
# Python environment
uv sync

# Fast smoke scan: no PyPI, no OSV, no uv subprocess checks
uv run pkgradar scan . --fast --no-enrich --no-advisories --quiet

# Web build (writes the committed bundle in src/pkgradar/webdist)
cd web && npm install && npm run build
cd .. && uv run pkgradar serve --open
```

For live frontend work, run the API and Vite side by side. Vite proxies `/api` to
`127.0.0.1:6767`, so the React app talks to a real scanner:

```bash
# terminal 1
uv run pkgradar serve . --port 6767

# terminal 2
cd web && npm run dev        # http://127.0.0.1:5173
```

`npm run build` runs `tsc --noEmit` and Vite. The compiled bundle is committed under
`src/pkgradar/webdist` so `uv tool install .` ships a working UI — rebuild it after
any `web/src` change. Do not edit the hashed files in `webdist` directly.

There is currently **no automated test suite or linter** configured; validate changes
with the smoke scan, `npm run build`, and a manual pass through the web UI / TUI.
[AGENTS.md](AGENTS.md) has the full validation checklist and the invariants to
preserve (read-only scanning, no interpreter execution, loopback trust model).

## Limitations

- Python/uv only. `pip`-only or Poetry projects are not discovered.
- Markers are evaluated using the running interpreter environment, overridden with the venv's
  Python version when available; optional/extra dependencies are shown but conflicts across
  mutually exclusive marker branches are intentionally not reported.
- PyPI/OSV enrichment is best-effort (cache + rate limits); use `--offline` for deterministic scans.
- `uv sync --dry-run` output is advisory — pkgradar reports what uv *would* do, it never runs it.
  Plans are skipped when the project interpreter is not a trusted symlink (e.g. Windows venvs).
- Environment compatibility (`uv pip check`) is not evaluated, because it executes the project
  interpreter; the venv check field is reported as `unknown`.
- Projects with dozens of direct dependencies get dense overviews; use depth, group and search
  filters, or the compact/layered layouts.
