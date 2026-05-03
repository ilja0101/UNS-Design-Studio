# UNS Design Studio V2 Roadmap

This roadmap captures the first V2 improvement track for the application. The goal is to keep the current demo experience intact while making the codebase safer to evolve, easier to deploy, and ready for automated container publishing.

## Current V2 branch

- Branch: `v2-improvements`
- Primary goal: harden the project foundation before larger refactors
- Delivery target: automated GitHub Container Registry publishing plus a Portainer-ready stack definition
- Status: Phases 1-5 implemented on this branch. Phase 3 was kept intentionally incremental to avoid destabilizing the working single-file runtime.

## Implementation phases

### Phase 1 — Deployment foundation

Status: Complete.

- Add a GitHub Actions workflow that builds and publishes the Docker image to GitHub Container Registry.
- Add a Portainer stack file that can deploy the published image without requiring a local build context.
- Add a container health check for the Flask dashboard endpoint.
- Keep the existing local `docker compose up` workflow intact.

### Phase 2 — Persistence and runtime safety

Status: Complete.

- Centralize JSON load/save helpers.
- Add atomic JSON writes using temporary files and replacement.
- Add clearer logging around failed config/state reads and writes.
- Review cross-process writes to `sim_state.json`, `bridge_config.json`, and `uns_config.json`.

### Phase 3 — Backend modularization

Status: Complete for this branch as low-risk modularization.

- Extracted simulator state merge/sync handling into `sim_state_service.py`.
- Extracted shared UNS tree traversal and bridge entry building helpers into `uns_tree.py`.
- Kept Flask route registration and subprocess process management in `app.py` for runtime stability until broader integration tests exist.
- Kept OPC dashboard polling in `app.py` to avoid changing live dashboard behavior without broader OPC integration coverage.

### Phase 4 — Test foundation

Status: Complete.

- Add pytest.
- Add tests for UNS tree traversal, payload formatting, simulation state merging, and recipe sync.
- Add workflow checks for Python syntax and unit tests.

### Phase 5 — Frontend maintainability

Status: Complete.

- Move large inline JavaScript blocks out of templates into static assets.
- Move CSS into static stylesheets.
- Keep pages visually unchanged while making browser code easier to lint and test.

## Validation status

- Python syntax validation: `python -m py_compile app.py factory.py bridge.py json_persistence.py sim_state_service.py uns_tree.py`.
- Unit tests: `python -m pytest`.
- Docker Compose validation: `docker compose config`.
- Portainer stack validation: `docker compose -f portainer-stack.yml config`.
- Runtime smoke testing: `python app.py` plus dashboard/API/static asset requests.

## Deployment conventions

- Default registry: GitHub Container Registry (`ghcr.io`).
- Default published image pattern: `ghcr.io/<owner>/<repository>:latest`.
- Portainer stack should deploy the registry image directly and persist runtime JSON configuration in a named Docker volume.

