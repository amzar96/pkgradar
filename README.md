# pkgradar

**A dependency radar for local [uv](https://docs.astral.sh/uv/) projects.** Point it at a folder,
and it maps every `uv.lock` + `.venv` underneath: the full dependency graph, what each version is
pinned by, what has drifted from the lock, which packages are outdated or vulnerable, and which
versions disagree across projects.

One scanner, two front ends: a dark, radar-style **web UI** and a **terminal UI**.

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

| Flag | Effect |
| --- | --- |
| `--offline` | Use cached PyPI data only, no network |
| `--no-enrich` | Skip PyPI lookups entirely (no latest/delta) |
| `--no-advisories` | Skip OSV lookups |
| `--fast` | Skip `uv lock --check` and `uv sync --dry-run` |

## Web UI

Hash-routed views, all backed by one `/api/scan` SSE stream:

- **`#fleet`** — every project found under the root, with package, outdated, advisory and drift counts.
- **`#topology`** — React Flow + ELK graph. Layouts: `auto` (radial under ~26 visible nodes, otherwise
  compact grid), `radial`, `compact`, `layered`. Depth selector (`1…all`), group filter, outdated /
  advisory filters, search dimming, path highlight to the selected node, `+N hidden` to expand.
- **`#packages`** — sortable table: locked, latest, semver delta, CVEs, risk, dependents, installed, depth.
- **`#conflicts`** — constraint intersections and lock/venv drift, each with the blame chain.
- **`#skew`** — one row per package, one column per project.

The graph reads from the **lockfile** (resolution truth) and reconciles against **installed
`dist-info` metadata** (environment truth). When the two disagree, nodes are marked
`missing` / `extra` / `version` and counted as drift.

## Terminal UI

```
1 Fleet     2 Topology     3 Conflicts     4 Skew     r Rescan     q Quit
```

- **Fleet** — project table with venv interpreter, lock state, drift.
- **Topology** — collapsible dependency tree per project; highlighting a package shows latest
  version, delta, installed version, risk factors, advisories (with fixed-in), and every package
  that requires it.
- **Conflicts / Skew** — the same data as the web tables.

Scanning happens in a background worker, so the UI stays responsive; `r` re-runs it.

## Read-only by design

pkgradar never mutates your projects. It only runs:

- `uv lock --check` (whether the lock matches `pyproject.toml`)
- `uv sync --dry-run` (planned installs/uninstalls — advisory only)
- `uv pip list` / `uv pip check` (installed truth, environment consistency)
- plain reads of `uv.lock`, `pyproject.toml`, and `.venv/**/dist-info/METADATA`

No `uv add`, `uv lock`, `uv sync`, or `pip install` is ever invoked. The scanner also strips
`VIRTUAL_ENV`, `CONDA_PREFIX` and `PYTHONHOME` from child processes so a scan can't be redirected
into the wrong environment.

## How it works

```
src/pkgradar/
  discover.py   walk a root, find uv projects (pyproject + uv.lock + .venv)
  locks.py      parse uv.lock into nodes/edges; workspace + group handling
  venvs.py      dist-info METADATA, uv pip list/check, drift + sync plan
  graph.py      BFS depths, orphans, cycles, root edges
  analyze.py    constraint intervals, conflict blame, risk score, cross-project skew
  pypi.py       PyPI JSON (latest, upload date, yanked/deprecated), disk cache
  osv.py        OSV querybatch advisories, per-package
  scanner.py    orchestration; emits progress/project/enrich/done events
  api.py        FastAPI + SSE + static web bundle
  cli.py        scan / serve / tui
  tui.py        Textual app
web/            React 19 + Vite + Tailwind v4 + @xyflow/react + elkjs + zustand
```

Conflict detection computes the **allowed interval per parent specifier** (marker-aware, using
installed metadata when lock edges are ambiguous) and flags packages whose resolved version falls
outside a parent's constraint. Lock/venv drift is reconciled separately from solver errors, so a
stale venv doesn't masquerade as an unsatisfiable dependency set.

## Development

```bash
uv sync
cd web && npm install && npm run build   # writes src/pkgradar/webdist
cd .. && uv run pkgradar serve --open
```

`npm run build` runs `tsc --noEmit` and Vite. The compiled bundle is committed under
`src/pkgradar/webdist` so `uv tool install .` ships a working UI.

## Limitations

- Python/uv only. `pip`-only or Poetry projects are not discovered.
- Markers are evaluated against the running interpreter; optional/extra dependencies are shown but
  conflicts across mutually exclusive marker branches are intentionally not reported.
- PyPI/OSV enrichment is best-effort (cache + rate limits); use `--offline` for deterministic scans.
- `uv sync --dry-run` output is advisory — pkgradar reports what uv *would* do, it never runs it.
- Projects with dozens of direct dependencies get dense overviews; use depth, group and search
  filters, or the compact/layered layouts.
