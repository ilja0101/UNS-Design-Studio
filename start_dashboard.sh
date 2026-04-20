#!/bin/bash
echo ""
echo " ╔══════════════════════════════════════════════════════════════╗"
echo " ║   UNS Design Studio       ║"
echo " ║   Starting web dashboard on http://localhost:5000            ║"
echo " ╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check for Flask
python3 -c "import flask" 2>/dev/null || pip3 install flask

# Open browser (works on macOS and most Linux desktops)
(sleep 2 && (open http://localhost:5000 2>/dev/null || xdg-open http://localhost:5000 2>/dev/null)) &

cd "$(dirname "$0")"
python3 app.py
