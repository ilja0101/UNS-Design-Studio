<div align="center">

# UNS Design Studio V2.0

**A self-contained Unified Namespace simulator for industrial IoT demos, training, and development.**

[![Version](https://img.shields.io/badge/version-v2.0-blue)](FEATURES.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-GHCR-2496ED?logo=docker&logoColor=white)](portainer-stack.yml)
[![OPC-UA](https://img.shields.io/badge/OPC--UA-4840-green)](https://opcfoundation.org/)
[![MQTT](https://img.shields.io/badge/MQTT%20%2F%20NATS-ready-orange)](https://mqtt.org/)

[Demo](#demo) · [Quick start](#quick-start) · [Docker](#docker) · [Portainer](#portainer--ghcr) · [Full docs](FEATURES.md)

</div>

---

## Demo

[![UNS Design Studio dashboard](docs/UNS_Design_StudioV3_2.JPG)](docs/UNS%20Design%20Studio%20v2.mp4)

| UNS Designer | Broker Bridge | Payload Designer |
|---|---|---|
| ![UNS Designer](docs/TopicTreeDesigner2.png) | ![Broker Bridge](docs/BrokerBridge.JPG) | ![Payload Designer](docs/Payload_Designer.JPG) |

## Features

- Browser dashboard for virtual plant control, recipes, metrics, anomaly injection, and process supervision.
- Visual ISA-95 / UNS tree designer backed by `uns_config.json`.
- Dynamic OPC-UA server generated from the configured UNS.
- OPC-UA to MQTT/NATS bridge with configurable broker, topic prefix, interval, and payload schemas.
- Live UNS viewer for broker-side topic validation.
- Asset library, importable enterprise templates, and configurable simulation profiles.
- Local Python, Docker Compose, Portainer, and GHCR deployment support.

## Quick start

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`. The Flask app starts the dashboard; use the UI/API controls to start the OPC-UA server and bridge.

Optional launch scripts:

```bat
start_dashboard.bat
```

```bash
bash start_dashboard.sh
```

Default endpoints:

- Dashboard: `http://localhost:5000`
- OPC-UA: `opc.tcp://localhost:4840`
- Anomaly TCP: `localhost:9999`

## Docker

```bash
docker compose up -d --build
docker compose logs -f
```

The local Compose build tags the image as `uns-design-studio:2.0` by default. Runtime state is stored in the `uns-design-studio-data` Docker volume.

## Portainer / GHCR

Use `portainer-stack.yml` to deploy the published image from GitHub Container Registry:

```text
ghcr.io/ilja0101/uns-design-studio:2.0
```

In Portainer, paste the stack file and optionally set:

```text
UNS_IMAGE=ghcr.io/ilja0101/uns-design-studio:2.0
```

## Runtime files

Root JSON files are live mutable state, not fixtures:

`uns_config.json`, `sim_state.json`, `bridge_config.json`, `server_config.json`, `payload_schemas.json`, `asset_library.json`

Docker seeds these files into `/data` on first boot and symlinks `/app/*.json` to `/data/*.json`.

## Validation

```bash
python -m py_compile app.py factory.py bridge.py
docker compose config
docker compose -f portainer-stack.yml config
python -m pytest
```

## License

MIT — see [LICENSE](LICENSE).

<div align="center">

Built by [Ilja Bartels](https://github.com/Ilja0101) for practical UNS and industrial IoT learning.

</div>
