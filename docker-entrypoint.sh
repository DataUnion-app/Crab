#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
  for directory in data logs taxonomy_data; do
    mkdir -p "$directory"
    if [ "$(stat -c '%u:%g' "$directory")" != "1001:1001" ]; then
      chown -R appuser:appuser "$directory"
    fi
  done
  export HOME=/home/appuser USER=appuser LOGNAME=appuser
  exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
fi

exec "$@"
