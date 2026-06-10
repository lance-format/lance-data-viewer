# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- API endpoint test suite (pytest + FastAPI TestClient) covering all six endpoints, pagination, column filtering, value serialization, and corrupted-dataset handling. The CI test job now runs it against every supported Lance version (#28).

### Fixed
- Frontend fetch calls now check `response.ok` before parsing JSON, so HTTP error responses surface as error states instead of being parsed as data (#27).
- `/rows` with unknown column names and `/vector/preview` with a missing or non-vector column now return 400 as intended; the error was previously masked as a generic 500 (#28).

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
