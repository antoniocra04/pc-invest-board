#!/bin/sh
set -e

case "${HEADLESS:-0}" in
  1|true|yes|on) ;;
  *)
    # Virtual screen for the headed Chromium.
    rm -f /tmp/.X99-lock
    Xvfb :99 -screen 0 1366x800x24 -nolisten tcp >/dev/null 2>&1 &
    export DISPLAY=:99
    ;;
esac

exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port "${PORT:-8080}"
