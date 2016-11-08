#!/bin/bash

cd $(dirname "${BASH_SOURCE[0]}")

echo service status:
vagrant ssh -- 'status warcprox ;
                status Xvnc ;
                status brozzler-worker ;
                status brozzler-dashboard ;
                status vnc-websock'
echo

vagrant ssh -- 'source /opt/brozzler-ve34/bin/activate && pip install pytest'
vagrant ssh -- 'source /opt/brozzler-ve34/bin/activate && py.test -v -s /brozzler/tests'
