# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- CI smoke test. Each build starts the image it just built and checks `/healthz`, `/datasets`, and the static files, before the image is published (#67).

### Changed
- GitHub Actions pinned to the majors that run on Node 24, before Node 20 leaves the runners (#60).
- FastAPI startup logging moved from the deprecated `on_event` decorator to a lifespan context manager (#77).

### Fixed
- `docker build` no longer fails with "the destination must be a directory and end with a /". `COPY backend/*.py .` needs a trailing slash when it copies more than one file. The classic builder rejected it, the BuildKit builder did not (#62).
- CI publishes no image until the test job passes. The build job now depends on the test job, so a failing test stops the release (#66).

## [0.3.1] - 2026-06-11

### Changed
- Maximum rows per page raised from 200 to 1000. The page-size dropdown gains 500 and 1000 options; the default stays at 50 (#58).

### Docs
- README screenshot replaced with one showing vector columns: CLIP badges, per-row sparklines, and the highlighted vector field in the schema panel. The old screenshot only showed scalar columns.

## [0.3.0] - 2026-06-10

### Added
- LanceDB 0.33.0 support with a matching container image tag. 0.33.0 is now the recommended version and carries the `latest`, `stable`, and `v{version}` tags (#53).
- API endpoint test suite (pytest + FastAPI TestClient) covering all six endpoints, pagination, column filtering, value serialization, and corrupted-dataset handling. The CI test job now runs it against every supported Lance version (#28).

### Fixed
- Frontend fetch calls now check `response.ok` before parsing JSON, so HTTP error responses surface as error states instead of being parsed as data (#27).
- `/rows` with unknown column names and `/vector/preview` with a missing or non-vector column now return 400 as intended; the error was previously masked as a generic 500 (#28).
- `/datasets` uses `list_tables()` on lancedb versions that have it, falling back to the deprecated `table_names()` on older ones (#54).

### Docs
- README refresh: corrected the supported-data-types section (variable-length float vectors render fully since #14; no 2048-dimension limit), documented the release image tags from #46, added test suite instructions, and linked CONTRIBUTING.md and CHANGELOG.md (#51).

## [0.2.0] - 2026-04-16

### Added
- LanceDB 0.29.2 support with a matching container image tag (#15).
- Rendering for `FixedSizeList` vectors and nested Arrow schemas, plus a UI word-wrap toggle for long text columns (#14).
- Configurable listening port via the `PORT` environment variable (#36).
- `VERSION` file at repo root as the single source of truth for the app version, consumed by `backend/app.py` at import and by the Docker build via `APP_VERSION` build-arg.
- `v{version}` GHCR tag on the canonical Lance variant when a `v*` git tag is pushed, so users can pin to an app release without specifying a Lance version.

### Fixed
- Native LanceDB pagination replaces full-table loads, avoiding OOM on large datasets (#18).
- Binary fields are decoded as UTF-8 where possible before falling back to base64 (#16).
- `docker/entrypoint.sh` is now used as the image ENTRYPOINT so `DATA_PATH` validation runs before uvicorn starts (#35).
- Version compatibility flags in `/healthz` use semantic comparison instead of string comparison (#34).

### Docs
- README updated for 0.29.2 as the recommended tag, registry URL corrected, and `PORT` documented (#37).
- docker-compose example added to the README for pipeline integration (#38).
- CONTRIBUTING.md describing design philosophy and constraints.
- GitHub issue templates for bug reports and feature requests.

## [0.1.0]

Initial release.
