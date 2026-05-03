# Project Documentation Rules (Non-Obvious Only)

- The repository is not a package/module layout; the canonical runtime flow is documented by reading `app.py`, `factory.py`, `bridge.py`, and root JSON files together.
- `docs/V2_ROADMAP.md` is the current improvement plan; `README.md` and `FEATURES.md` describe the existing demo/product behavior.
- Example UNS imports in `example_UNS_jsons_to_import/` are useful fixtures for understanding valid `uns_config.json` shapes.
- The browser pages are large self-contained templates; there is no separate frontend build pipeline yet.

