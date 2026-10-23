# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
aims to follow [Semantic Versioning](https://semver.org/) once it has a first release.

## [Unreleased]

### Added
- Repository hygiene: `.gitignore` (secrets, datasets, model artifacts, local databases),
  `.gitattributes` (LF normalisation), `.editorconfig`. (T001)
- Project records: roadmap, project status, decisions log, work log, this changelog. (T001)
- `CLAUDE.md` working agreement for Claude Code sessions. (T001)
- Product and dataset specifications moved, unchanged, to `docs/specs/`. (T001)
- Backend foundation: `wattwise` Python package with environment-based settings, a FastAPI app
  factory, and a `GET /api/v1/health` liveness endpoint with OpenAPI docs. (T002)
- Backend tooling: pytest (10 tests), ruff lint and format, strict mypy. (T002)
- `.env.example` documenting `WATTWISE_ENVIRONMENT`. (T002)

### Fixed
- The audit records wrongly stated which credential git pushes with. They now describe the real
  cause of the initial HTTP 403 push failure. (T001)

### Changed
- This repository now commits and pushes as the owner's personal account, `shvhjSB`, through
  repository-local git configuration (D006). (T002)
