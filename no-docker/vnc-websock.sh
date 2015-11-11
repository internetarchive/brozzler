#!/bin/sh
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH=/home/nlevitt/workspace/websockify/websockify-ve34/lib/python3.4/site-packages:/home/nlevitt/workspace/websockify exec /home/nlevitt/workspace/websockify/websockify-ve34/bin/websockify 0.0.0.0:8901 localhost:5901 >> /home/nlevitt/workspace/brozzler/no-docker/websockify-`hostname -s`.out 2>&1
