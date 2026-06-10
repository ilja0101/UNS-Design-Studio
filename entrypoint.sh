#!/bin/sh
# On first boot: seed /data from the bundled defaults in the image.
# On every boot: symlink /app/*.json → /data/*.json so Python finds them
#                at the expected paths.

mkdir -p /data

for cfg in uns_config.json bridge_config.json payload_schemas.json server_config.json asset_library.json sim_state.json; do
    if [ ! -f "/data/$cfg" ]; then
        echo "[init] Seeding $cfg into persistent volume"
        cp "/app/$cfg" "/data/$cfg"
    fi
    ln -sf "/data/$cfg" "/app/$cfg"
done

if [ ! -f "/data/visualization.json" ]; then
    echo "[init] Creating visualization.json in persistent volume"
    printf '{"version":1,"entities":{},"links":[],"gauges":[],"animations":[]}\n' > /data/visualization.json
fi
ln -sf "/data/visualization.json" "/app/visualization.json"

export UNS_DATA_DIR=/data

exec "$@"
