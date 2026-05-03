#!/bin/bash
echo ""
echo " ╔══════════════════════════════════════════════════════════════╗"
echo " ║   UNS Design Studio       ║"
echo " ║   Starting web dashboard on http://localhost:5000            ║"
echo " ╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check for Flask
python3 -c "import flask" 2>/dev/null || pip3 install flask

# Open browser when the Flask app is ready (works on macOS and most Linux desktops)
(
  for i in $(seq 1 30); do
    if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/status', timeout=1).read()" >/dev/null 2>&1; then
      open http://localhost:5000 2>/dev/null || xdg-open http://localhost:5000 2>/dev/null
      exit 0
    fi
    sleep 1
  done
) &

cd "$(dirname "$0")"
python3 app.py
