# Agent & MCP

UNS Design Studio can be driven by a language model: a built-in chat agent on
the **Agent** page, and an **MCP server** so an outside agent — Claude Desktop,
Claude Code, UNS-Industrial-AI, anything that speaks MCP — can do the same job
from outside the browser.

Both run the *same* tools. There is one registry ([`uds_agent/tools.py`](../uds_agent/tools.py))
and no second definition of what an agent may do to a UDS, so the built-in
agent and an external one are always exactly as capable as each other.

---

## The idea

Give the agent your organisation's **topic policy** and ask it to model a
simulation. It reads the rulebook, builds the ISA-95 tree, instantiates real
equipment from the asset library, checks its own work against the policy, fixes
what it broke, and shows you the topics the bridge will actually publish.

```
you ── policy + "model me a dairy site in Veghel"
        │
        ├─ policy_get           read the rulebook
        ├─ uns_overview         see what is already there
        ├─ uns_replace_subtree  generate the site
        ├─ uns_add_asset        real pumps, boilers, packing machines
        ├─ policy_check         grade it  →  12 violations
        ├─ policy_conform_names fix the naming
        ├─ policy_check         grade it  →  ok
        └─ topics_preview       "here is your namespace"
```

Every write is snapshotted first, so anything the agent does is undoable — from
the **Undo** tab on the Agent page, or with the `uns_revert` tool.

---

## Setting it up

### The built-in agent

Settings → **Agent**. Any OpenAI-compatible endpoint works:

| Provider | Endpoint | Model |
|---|---|---|
| Azure AI Foundry | `https://<resource>.openai.azure.com/openai/v1` | your deployment name |
| OpenAI | `https://api.openai.com/v1` | `gpt-4.1` |
| OpenRouter | `https://openrouter.ai/api/v1` | e.g. `anthropic/claude-sonnet-4` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5:14b` |
| vLLM / LM Studio | your server's `/v1` | the served model |

Or set them in the environment instead, which then wins over the saved values:

```bash
UDS_LLM_ENDPOINT=https://…/v1
UDS_LLM_API_KEY=…
UDS_LLM_MODEL=gpt-4.1
```

The API key is stored in `agent_config.json` under the data dir and is never
sent back to the browser.

**No LLM?** Leave it blank. The MCP server works on its own — the chat page
just tells you it is not configured.

### The MCP server

On by default, at `POST /mcp` on the dashboard's own port, gated by a bearer
token minted on first use. Settings → Agent → **MCP server** shows the endpoint
and the token, and can rotate it, switch writes off, or turn MCP off entirely.

```bash
UDS_MCP_TOKEN=…      # pin the token instead of using the generated one
UDS_MCP_ENABLED=0    # switch MCP off
```

`GET /mcp/info` is unauthenticated and reports whether MCP is on, the protocol
revision, and which tools it offers — handy for a health check or for wiring up
a client. It exposes no token and no model content.

---

## Connecting an agent

### Streamable HTTP (in-process — the usual choice)

```jsonc
{
  "mcpServers": {
    "uns-design-studio": {
      "type": "http",
      "url": "http://localhost:5000/mcp",
      "headers": { "Authorization": "Bearer <token from Settings>" }
    }
  }
}
```

Tools run inside the dashboard process, so a write lands immediately — the OPC
address space restarts and the bridge picks the change up, exactly as if you
had saved from the Designer.

### stdio (a desktop agent on the same machine)

```bash
python -m uds_mcp stdio --uds http://localhost:5000
```

```jsonc
{
  "mcpServers": {
    "uns-design-studio": {
      "command": "python",
      "args": ["-m", "uds_mcp", "stdio", "--uds", "http://localhost:5000"],
      "cwd": "/path/to/UNS-Design-Studio"
    }
  }
}
```

No token — the OS process boundary is the gate. Add `--read-only` to hide every
write tool from that connection. If the UDS is behind HTTP Basic, pass
`--uds-user` / `--uds-password`.

### Its own process or container

For a separate trust boundary — a different token from the dashboard's own
auth, no UI, nothing of `app.py` in the process:

```bash
docker build -f Dockerfile.mcp -t uds-mcp .
docker run -e UDS_MCP_TOKEN=… -e UDS_URL=http://uds:5000 -p 8060:8060 uds-mcp
```

This is the shape `UNS-Knowledge-Graph`'s `kg-mcp` uses. It reaches the UDS over
its REST API, so it can sit anywhere.

---

## The topic policy

A policy is one document with two halves.

**Machine-checkable**, driving `policy_check`:

```json
{
  "name": "Acme UNS Topic Policy v3",
  "separator": "/",
  "prefix": "uns",
  "caseRule": "kebab",
  "maxTopicLength": 180,
  "levels": [
    { "type": "enterprise", "required": true, "allowed": ["acme"] },
    { "type": "site",       "required": true, "pattern": "^[a-z]{2}-[a-z0-9-]+$" },
    { "type": "area",       "required": true },
    { "type": "workUnit",   "required": false }
  ],
  "tag": { "caseRule": "snake", "qualifiers": ["data", "command", "state"] },
  "forbiddenParts": ["test", "tmp"],
  "notes": "Sites are ISO-3166 country code, dash, town. No vendor names in topics."
}
```

**`notes`** is the other half: the prose a regex cannot capture. It is injected
verbatim into the agent's system prompt every turn and the agent is told to
treat it as binding.

`caseRule` is one of `kebab`, `snake`, `lower`, `upper`, `pascal`, `any`. A
level's explicit `pattern` overrides its case rule.

The checker runs the bridge's own tree walk
([`uns_tree.build_bridge_entries`](../uns_tree.py)), so what it validates is
literally what would be published. It reports:

| Code | Meaning |
|---|---|
| `name.pattern` / `tag.pattern` | a name breaks the case rule or pattern |
| `name.allowed` / `name.forbidden` | outside an allowed set, or on the deny list |
| `name.separator` | a name contains the topic separator |
| `level.missing` / `level.order` / `level.undeclared` | ISA-95 ladder problems |
| `tag.qualifier` | a qualifier outside the allowed set |
| `topic.duplicate` | two tags collapse onto one topic |
| `topic.length` | over `maxTopicLength` |

Edit it on the Agent page's **Policy** tab, over `GET|POST /api/agent/policy`,
or just paste your policy into the chat and ask the agent to store it.

---

## Tools

Read-only tools are available on every connection; write tools are hidden when
writes are disabled (Settings, or `--read-only`).

**Inspect** — `uns_overview`, `uns_browse`, `uns_search`, `uns_get_node`,
`sim_status`, `asset_library`, `simulation_profiles`, `topics_preview`

**Model** — `uns_add_node`, `uns_update_node`, `uns_delete_node`,
`uns_move_node`, `uns_set_tags`, `uns_delete_tags`, `uns_add_asset`,
`uns_replace_subtree`

**Policy** — `policy_get`, `policy_set`, `policy_check`, `policy_conform_names`,
`policy_suggest_name`

**Undo** — `uns_snapshots`, `uns_revert`

**Run it** — `sim_control`, `plant_control`, `anomaly_inject`, `bridge_config`,
`payload_schemas`, `plc_simulators`

Two of these do most of the work when building something new:

- **`uns_add_asset`** instantiates an asset-library template — a centrifugal
  pump arrives with all eleven of its tags, correct units and simulation
  profiles, in one call. Tag names are rewritten into the policy's case rule on
  the way in (pass `conform_names: false` to keep the template's own).
- **`uns_replace_subtree`** takes a whole nested tree, so a site is one call
  rather than fifty.

Paths are `/`-joined node **names** from the root — `acme/nl-veghel/mixing`.
The root's own name is optional, so a path copied out of a topic works too.

---

## How it fits together

```
                    ┌──────────────────────────────┐
  Agent page  ─────►│  uds_agent/loop.py           │
  (SSE stream)      │    ↕ uds_agent/llm.py        │──► your LLM endpoint
                    └──────────────┬───────────────┘
                                   │
  external agent ──► /mcp ────────►├─ uds_agent/tools.py ──┐
  (bearer token)                   │   one registry        │
                                   │                       ▼
  python -m uds_mcp ──────────────►┘              uds_agent/backend.py
  (stdio / own process)                            ├─ Direct: the app's own
                                                   │  routes, in-process
                                                   └─ Http: a remote UDS
```

`DirectBackend` re-enters the dashboard's real HTTP handlers through Quart's
test client rather than reimplementing them, which is why an agent's UNS save
restarts the OPC server and the bridge just like the Designer's does. Those
in-process calls carry a per-boot random header that `app.py` accepts, so the
tools work when the dashboard is behind HTTP Basic without ever handling the
operator's password.

## Runtime files

Under the data dir (`UNS_DATA_DIR`, else `/data`, else the repo):

| File | What |
|---|---|
| `agent_config.json` | LLM endpoint/key/model, agent behaviour, MCP token |
| `topic_policy.json` | the active topic policy |
| `agent/conversations/*.json` | chat history, replayable into the model |
| `agent/snapshots/*.json` | the undo history (last 30 model states) |
