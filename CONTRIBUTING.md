# Contributing to Lance Data Viewer

Thanks for your interest in contributing. This document covers what the
project is, the design constraints that shape it, and how to propose changes.

## What This Project Is

Lance Data Viewer is a read-only, mount-and-go web UI for browsing Lance and
LanceDB tables. The intended flow is:

1. Point a Docker container at a directory of Lance files.
2. Open a browser.
3. Browse.

There is no setup, no database to configure, no writes. The viewer is meant
for local development, data inspection, and sanity-checking datasets produced
by other pipelines.

## Design Constraints

A few constraints are load-bearing. They are the reason the project is small,
fast to start, and easy to drop into a Docker Compose stack next to other
services. Proposals that move away from them need a strong justification and
are best discussed in an issue before code is written.

### Vanilla JS, no build step

The frontend is plain JavaScript, HTML, and CSS served directly from the
container. There is no Webpack, Vite, esbuild, `tsc`, or `npm install` in the
build path. This keeps the container image small, the contributor onboarding
bar low, and the edit-refresh loop instant.

Proposals to introduce TypeScript, React, Vue, Svelte, jQuery, or a CSS
framework such as Tailwind fall under this constraint.

### GET-only, stateless API

Every endpoint in `backend/app.py` is a GET. There are no sessions, no
server-side state between requests, and no POST/PUT/DELETE surface. The
viewer's single job is to read Lance files and serialize them to JSON.

Proposals that introduce POST endpoints, server-side query state, or filtering
that accepts raw SQL from the client fall under this constraint.

### No metadata database

The Lance files in the mounted directory are the only source of truth. The
viewer does not maintain a separate SQLite, DuckDB, or Redis alongside them.
Adding one would introduce a lifecycle (migrations, eviction, consistency)
that conflicts with the mount-and-go model.

### No in-app authentication

There is no login, no token check, and no RBAC. Deployments that need access
control are expected to run the container on localhost or behind a reverse
proxy (Nginx, Traefik, Caddy) that handles auth at the edge.

### Read-only access

The viewer never writes to the mounted Lance directory. The examples in the
README mount `/data` with `:ro`, and the code path contains no write
operations. This is deliberate: the viewer should be safe to point at
production data without any fear of corruption.

## Proposing Changes

For small bug fixes and direct improvements, opening a PR is fine. For
anything that touches the design constraints above, adds a new dependency, or
meaningfully changes the architecture, please open an issue first so the
approach can be discussed before code is written.

Recent examples of the "issue first" path:

- Adding media previews for columns that reference external assets: see the
  approach discussion in #29.
- Replacing the vanilla JS frontend with a framework or toolkit: see #5
  (TypeScript) and #39 (jQuery + DataTables + DuckDB) for prior discussions of
  why this direction does not fit.

## Where To Start

The improvement plan lives in the issue tracker. A few good starting points
for new contributors:

- Issues labeled `bug` for direct fixes.
- Issues labeled `documentation` for low-risk contributions while learning the
  codebase.
- Issues labeled `enhancement` for feature work. Read the design constraints
  above first.

## Development Workflow

```bash
# Build with a specific Lance version (default: 0.36.0)
docker build -f docker/Dockerfile \
    --build-arg LANCEDB_VERSION=0.36.0 \
    -t lance-data-viewer:dev .

# Run with your data
docker run --rm -p 8080:8080 -e DATA_PATH=/data -v $(pwd)/data:/data:ro lance-data-viewer:dev

# Open the UI
open http://localhost:8080
```

No frontend build step. Edit files in `web/vanilla/` and reload the browser.
