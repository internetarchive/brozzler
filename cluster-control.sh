#!/bin/bash

if [ `hostname -s` != wbgrp-svc107 ] ; then
    echo $0 expects to run on wbgrp-svc107
    exit 1
fi

_status() {
	something_running=1

	pids=( $(pgrep -f /home/nlevitt/tmp/brozzler-venv/bin/warcprox) )
	pids=${pids[*]}
	if [ -n "$pids" ] ; then 
		echo "warcprox is running: pids $pids"
		something_running=0
	else
		echo "warcprox is not running"
	fi

	pids=( $(pgrep -f /home/nlevitt/tmp/brozzler-venv/bin/brozzler-worker) )
	pids=${pids[*]}
	if [ -n "$pids" ] ; then 
		echo "brozzler-workers are running: pids $pids"
		something_running=0
	else
		echo "brozzler-workers are not running"
	fi

	pids=( $(pgrep -f /home/nlevitt/workspace/pygwb/pygwb-ve27/bin/gunicorn) )
	pids=${pids[*]}
	if [ -n "$pids" ] ; then 
		echo "pywayback is running: pids $pids"
		something_running=0
	else
		echo "pywayback is not running"
	fi

	pids=( $(pgrep -f /home/nlevitt/workspace/ait5/scripts/brozzler-job-starter.py) )
	pids=${pids[*]}
	if [ -n "$pids" ] ; then 
		echo "brozzler-job-starter.py is running: pids $pids"
		something_running=0
	else
		echo "brozzler-job-starter.py is not running"
	fi

	return $something_running
}

_fullstatus() {
	warcprox_pids=( $(pgrep -f /home/nlevitt/tmp/brozzler-venv/bin/warcprox) )
	worker_pids=( $(pgrep -f /home/nlevitt/tmp/brozzler-venv/bin/brozzler-worker) )
	pywayback_pids=( $(pgrep -f /home/nlevitt/workspace/pygwb/pygwb-ve27/bin/gunicorn) )
	job_starter_pids=( $(pgrep -f /home/nlevitt/workspace/ait5/scripts/brozzler-job-starter.py) )

	pids="${warcprox_pids[*]} ${worker_pids[*]} ${pywayback_pids[*]} ${job_starter_pids[*]}"
	if [ "$pids" != "   " ] ; then
		PS_FORMAT=user,pid,tid,ppid,pgid,sid,pri,nice,psr,%cpu,%mem,tty,stat,stime,time,args ps ww -H $pids
		echo
	fi

	[ -z "${warcprox_pids[*]}" ] && echo "warcprox is not running"
	[ -z "${worker_pids[*]}" ] && echo "brozzler-workers are not running"
	[ -z "${pywayback_pids[*]}" ] && echo "pywayback is not running"
	[ -z "${job_starter_pids[*]}" ] && echo "brozzler-job-starter.py is not running"
}

_stop() {
	pkill -f /home/nlevitt/workspace/pygwb/pygwb-ve27/bin/gunicorn
	pkill -f /home/nlevitt/workspace/ait5/scripts/brozzler-job-starter.py
	pkill -f /home/nlevitt/tmp/brozzler-venv/bin/warcprox
	# pkill -f /home/nlevitt/tmp/brozzler-venv/bin/brozzler-worker
	for node in aidata{400,400-bu,401-bu} ; do
		ssh $node pkill -f /home/nlevitt/tmp/brozzler-venv/bin/brozzler-worker
	done
	sleep 3
	for node in aidata{400,400-bu,401-bu} ; do
		ssh $node killall chromium-browser
	done
	
	if _status ; then
		while _status > /dev/null ; do sleep 0.5 ; done
	fi
}

_reset() {
	if _status ; then
		echo "looks like something's still running, run '$0 stop' before resetting"
		exit 1
	fi

	tstamp=$(date +"%Y%m%d%H%M%S") 
	echo "renaming rethinkdb database archiveit_brozzler to archiveit_brozzler_$tstamp"
	PYTHONPATH=/home/nlevitt/tmp/brozzler-venv/lib/python3.4/site-packages python3.4 <<EOF
import rethinkdb as r
with r.connect("wbgrp-svc035") as conn:
    r.db("archiveit_brozzler").config().update({"name":"archiveit_brozzler_$tstamp"}).run(conn)
EOF

	set -e
	mv -v /1/brzl /tmp/brzl.$tstamp
	mkdir -vp /1/brzl/logs
}

_start() {
	if _status ; then
		echo "can't start because something's still running"
		exit 1
	fi

	set -e
	set -x 

	PYTHONPATH=/home/nlevitt/tmp/brozzler-venv/lib/python3.4/site-packages:/home/nlevitt/workspace/brozzler:/home/nlevitt/workspace/warcprox:/home/nlevitt/workspace/ait5 /home/nlevitt/tmp/brozzler-venv/bin/warcprox --dir=/1/brzl/warcs --rethinkdb-servers=wbgrp-svc020,wbgrp-svc035,wbgrp-svc036 --rethinkdb-db=archiveit_brozzler --rethinkdb-big-table --cacert=/1/brzl/warcprox-ca.pem --certs-dir=/1/brzl/certs --address=0.0.0.0 --base32 --gzip --rollover-idle-time=180 --kafka-broker-list=qa-archive-it.org:6092 --kafka-capture-feed-topic=ait-brozzler-captures &>/1/brzl/logs/warcprox.out &

	sleep 5

        PYTHONPATH=/home/nlevitt/tmp/brozzler-venv/lib/python3.4/site-packages:/home/nlevitt/workspace/brozzler:/home/nlevitt/workspace/warcprox:/home/nlevitt/workspace/ait5 /home/nlevitt/workspace/ait5/scripts/brozzler-job-starter.py &> /1/brzl/logs/ait-job-starter.out &

	sleep 5

	for node in aidata{400,400-bu,401-bu} ; do
	    ssh -fn $node 'PYTHONPATH=/home/nlevitt/tmp/brozzler-venv/lib/python3.4/site-packages XAUTHORITY=/tmp/Xauthority.nlevitt DISPLAY=:1 /home/nlevitt/tmp/brozzler-venv/bin/brozzler-worker --rethinkdb-servers=wbgrp-svc036,wbgrp-svc020,wbgrp-svc035 --rethinkdb-db=archiveit_brozzler --max-browsers=10' &> /1/brzl/logs/brozzler-worker-$node.out
	done

	PYTHONPATH=/home/nlevitt/workspace/pygwb/pygwb-ve27/lib/python2.7/site-packages:/home/nlevitt/workspace/pygwb WAYBACK_CONFIG=/home/nlevitt/workspace/pygwb/gwb.yaml PATH=/home/nlevitt/workspace/pygwb/pygwb-ve27/bin:/usr/bin:/bin /home/nlevitt/workspace/pygwb/start-gwb.sh &> /1/brzl/logs/pywayback.out &

	set +x

	echo
	echo logs are in /1/brzl/logs
	echo warcs are in /1/brzl/warcs
}

if [ $# != 1 ] ; then
	echo "Usage: $0 status|fullstatus|start|stop|restart|reset"
	exit 1
elif [ $1 = 'fullstatus' ] ; then
	_fullstatus
elif [ $1 = 'status' ] ; then
	_status
elif [ $1 = 'stop' ] ; then
	_stop
elif [ $1 = 'start' ] ; then
	_start
elif [ $1 = 'restart' ] ; then
	_stop
	_start
elif [ $1 = 'reset' ] ; then
	_reset
else
	echo "Usage: $0 status|fullstatus|start|stop|restart|reset"
	exit 1
fi

