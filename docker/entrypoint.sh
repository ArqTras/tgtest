#!/bin/sh
set -e
mkdir -p /data /sources
if [ -z "$(find /sources -type f -print -quit)" ]; then
  cp -a /opt/seed-sources/. /sources/
fi
exec python -m app
