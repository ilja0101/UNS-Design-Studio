# UNS Design Studio V2 Roadmap

This roadmap captures the first V2 improvement track for the application. The goal is to keep the current demo experience intact while making the codebase safer to evolve, easier to deploy, and ready for automated container publishing.

## Current V2 branch

- Branch: `v2-improvements`
- Primary goal: harden the project foundation before larger refactors
- Delivery target: automated GitHub Container Registry publishing plus a Portainer-ready stack definition

## Implementation phases

### Phase 1 — Deployment foundation

- Add a GitHub Actions workflow that builds and publishes the Docker image to GitHub Container Registry.
- Add a Portainer stack file that can deploy the published image without requiring a local build context.
- Add a container health check for the Flask dashboard endpoint.
- Keep the existing local `docker compose up` workflow intact.

### Phase 2 — Persistence and runtime safety

- Centralize JSON load/save helpers.
- Add atomic JSON writes using temporary files and replacement.
- Add clearer logging around failed config/state reads and writes.
- Review cross-process writes to `sim_state.json`, `bridge_config.json`, and `uns_config.json`.

### Phase 3 — Backend modularization

- Split Flask routes into blueprints.
- Move simulator state handling into a dedicated service module.
- Move process management for `factory.py` and `bridge.py` into a dedicated service module.
- Move OPC dashboard polling and metric collection into a dedicated module.

### Phase 4 — Test foundation

- Add pytest.
- Add tests for UNS tree traversal, payload formatting, simulation state merging, and recipe sync.
- Add workflow checks for Python syntax and unit tests.

### Phase 5 — Frontend maintainability

- Move large inline JavaScript blocks out of templates into static assets.
- Move CSS into static stylesheets.
- Keep pages visually unchanged while making browser code easier to lint and test.

## Deployment conventions

- Default registry: GitHub Container Registry (`ghcr.io`).
- Default published image pattern: `ghcr.io/<owner>/<repository>:latest`.
- Portainer stack should deploy the registry image directly and persist runtime JSON configuration in a named Docker volume.

