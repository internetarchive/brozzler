#!/bin/bash

echo service status:
vagrant ssh -- 'status warcprox ;
                status Xvnc ;
                status brozzler-worker ;
                status brozzler-webconsole ;
                status vnc-websock'
echo

vagrant ssh -- 'source brozzler-ve34/bin/activate && pip install pytest'
vagrant ssh -- 'source brozzler-ve34/bin/activate && py.test -v -s /brozzler/tests'
