# Project Debug Rules (Non-Obvious Only)

- Dashboard up does not mean OPC-UA is running; `app.py` starts `factory.py` only through server control paths and polls port 4840 separately.
- Bridge status comes from child-process stdout, not an API inside `bridge.py`; missing `[BRIDGE_STATS]` lines means dashboard stats stay stale.
- Many config/read/traversal failures are swallowed for demo resilience; inspect `/api/logs`, subprocess stdout, and the JSON files directly when behavior looks frozen.
- If UNS edits appear ignored, remember `/api/uns` restarts `factory.py` only when it was already running and restarts the bridge after a delayed thread.
- In Docker, inspect `/data/*.json` for real runtime config; `/app/*.json` are symlinks created by `entrypoint.sh`.

