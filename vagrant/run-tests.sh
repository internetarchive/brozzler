#!/bin/bash
#
# any arguments are passed on to py.test
# so for example to run only "test_obey_robots" you could run
# ./run-tests.sh -k test_obey_robots
#

cd $(dirname "${BASH_SOURCE[0]}")

vagrant up

echo service status:
vagrant ssh -- 'status warcprox ;
                status Xvnc ;
                status brozzler-worker ;
                status brozzler-dashboard ;
                status vnc-websock'
echo

vagrant ssh -- 'set -x ; source /opt/brozzler-ve34/bin/activate && pip install pytest && pip install --upgrade --pre "warcprox>=2.1b1.dev71"'
vagrant ssh -- "source /opt/brozzler-ve34/bin/activate && DISPLAY=:1 py.test -v /brozzler/tests $@"
