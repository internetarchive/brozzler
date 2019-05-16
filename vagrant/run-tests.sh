#!/bin/bash
#
# any arguments are passed on to py.test
# so for example to run only "test_obey_robots" you could run
# ./run-tests.sh -k test_obey_robots
#

cd $(dirname "${BASH_SOURCE[0]}")

vagrant up

echo service status:
vagrant ssh -- 'sudo svstat /etc/service/warcprox ;
                sudo svstat /etc/service/Xvnc ;
                sudo svstat /etc/service/brozzler-worker ;
                sudo svstat /etc/service/brozzler-dashboard ;
                sudo svstat /etc/service/vnc-websock'
echo

vagrant ssh -- 'set -x ; source /opt/brozzler-ve3/bin/activate && pip install pytest==4.3.0 && pip install --upgrade --pre "warcprox>=2.1b1.dev86"'
vagrant ssh -- "source /opt/brozzler-ve3/bin/activate && DISPLAY=:1 py.test --tb=native -v /brozzler/tests $@"
