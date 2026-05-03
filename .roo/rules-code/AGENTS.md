# Project Coding Rules (Non-Obvious Only)

- Preserve the bare-site plant key format (`BusinessUnit|SiteName`) even though OPC-UA site objects are named `Factory{SiteName}`.
- When editing UNS tag traversal, update all three walkers together: dashboard metric discovery in `app.py`, OPC address-space creation in `factory.py`, and bridge entry building in `bridge.py`.
- Keep `[BRIDGE_STATS] ` stdout framing in `bridge.py`; `app.py` depends on that exact prefix for live bridge stats.
- Do not treat root JSON files as static seed data only; in local mode they are live mutable state, and in Docker they are symlink targets into `/data`.
- If adding JSON writes, match existing readable formatting (`indent=2`, `ensure_ascii=False` where UI/config data may contain Unicode) and prefer atomic writes in V2 work.

