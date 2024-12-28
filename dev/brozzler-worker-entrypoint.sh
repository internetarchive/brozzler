#!/bin/bash
set -e

venv="/opt/brozzler-worker-venv"

if [ -f "/brozzler/setup.py" ]; then
  echo "#### Installing /brozzler in $venv"
  $venv/bin/pip install --disable-pip-version-check -e /brozzler[yt_dlp] --quiet
  $venv/bin/pip install --disable-pip-version-check rethinkdb==2.4.9 doublethink==0.4.9
fi

echo "Running brozzler-worker"

su brozzler-worker /run-brozzler-worker.sh

echo "Run worker like: /run-brozzler-worker.sh"
su brozzler-worker

/bin/bash
