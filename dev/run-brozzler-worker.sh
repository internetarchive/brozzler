#!/bin/bash
source /opt/brozzler-worker-venv/bin/activate

brozzler-worker --verbose \
  --rethinkdb-servers=rethinkdb \
  --rethinkdb-db=brozzler_dev \
  --max-browsers=1 \
  --warcprox-auto
