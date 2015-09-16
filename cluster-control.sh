#!/bin/bash

if [ `hostname -s` != wbgrp-svc107 ] ; then
    echo $0 expects to run on wbgrp-svc107
    exit 1
fi

_status() {
	something_running=1

	warcprox_pids=( $(pgrep -f /home/nlevitt/workspace/warcprox/warcprox-ve34/bin/warcprox) )
	worker_pids=( $(pgrep -f /home/nlevitt/workspace/brozzler/brozzler-ve34/bin/brozzler-worker) )
	pywayback_pids=( $(pgrep -f /home/nlevitt/workspace/pygwb/pygwb-ve27/bin/gunicorn) )
	ait_brozzler_boss=( $(pgrep -f /home/nlevitt/workspace/ait5/scripts/ait-brozzler-boss.py) )
	ait5_pids=( $(pgrep -f 0.0.0.0:8888) )

	pids="${warcprox_pids[*]} ${worker_pids[*]} ${pywayback_pids[*]} ${ait_brozzler_boss[*]} ${ait5_pids[*]}"
	if [ "$pids" != "    " ] ; then
		PS_FORMAT=user,pid,tid,ppid,pgid,sid,pri,nice,psr,%cpu,%mem,tty,stat,stime,time,args ps ww -H $pids
		echo
		something_running=0
	fi

	[ -z "${warcprox_pids[*]}" ] && echo "$0: warcprox is not running"
	[ -z "${worker_pids[*]}" ] && echo "$0: brozzler-workers are not running"
	[ -z "${pywayback_pids[*]}" ] && echo "$0: pywayback is not running"
	[ -z "${ait_brozzler_boss[*]}" ] && echo "$0: ait-brozzler-boss.py is not running"
	[ -z "${ait5_pids[*]}" ] && echo "$0: ait5 is not running"

	return $something_running
}

_stop() {
	if _status ; then
		pkill -f /home/nlevitt/workspace/pygwb/pygwb-ve27/bin/gunicorn
		pkill -f /home/nlevitt/workspace/ait5/scripts/ait-brozzler-boss.py
		pkill -f /home/nlevitt/workspace/warcprox/warcprox-ve34/bin/warcprox
		pkill -f 0.0.0.0:8888
		# pkill -f /home/nlevitt/workspace/brozzler/brozzler-ve34/bin/brozzler-worker
		for node in aidata{400,400-bu,401-bu} ; do
			ssh $node pkill -f /home/nlevitt/workspace/brozzler/brozzler-ve34/bin/brozzler-worker
		done
		sleep 3
		for node in aidata{400,400-bu,401-bu} ; do
			ssh $node killall chromium-browser
		done
	fi
	
	if _status > /dev/null ; then
		while _status > /dev/null ; do sleep 0.5 ; done
	fi

	echo "$0: all services stopped"
}

_reset() {
	if _status ; then
		echo "$0: looks like something's still running, run '$0 stop' before resetting"
		exit 1
	fi

	tstamp=$(date +"%Y%m%d%H%M%S") 
	echo "renaming rethinkdb database archiveit_brozzler to archiveit_brozzler_$tstamp"
	PYTHONPATH=/home/nlevitt/workspace/brozzler/brozzler-ve34/lib/python3.4/site-packages python3.4 <<EOF
import rethinkdb as r
with r.connect("wbgrp-svc035") as conn:
    r.db("archiveit_brozzler").config().update({"name":"archiveit_brozzler_$tstamp"}).run(conn)
EOF
	mysql -hwbgrp-svc107 -P6306 -uarchiveit -parchiveit archiveit3 -e "update CrawlJob set status='FINISHED_ABNORMAL', endDate=now() where status='ACTIVE'"

	set -e
	mv -v /1/brzl /tmp/brzl.$tstamp
	mkdir -vp /1/brzl/{warcs,logs}
}

_start() {
	if _status > /dev/null ; then
		echo "$0: can't start because something's still running"
		exit 1
	fi

	set -e

	echo $0: starting warcprox
	PYTHONPATH=/home/nlevitt/workspace/warcprox/warcprox-ve34/lib/python3.4/site-packages /home/nlevitt/workspace/warcprox/warcprox-ve34/bin/warcprox --dir=/1/brzl/warcs --rethinkdb-servers=wbgrp-svc020,wbgrp-svc035,wbgrp-svc036 --rethinkdb-db=archiveit_brozzler --rethinkdb-big-table --cacert=/1/brzl/warcprox-ca.pem --certs-dir=/1/brzl/certs --address=0.0.0.0 --base32 --gzip --rollover-idle-time=180 --kafka-broker-list=qa-archive-it.org:6092 --kafka-capture-feed-topic=ait-brozzler-captures &>>/1/brzl/logs/warcprox.out &

	sleep 5

	echo $0: starting ait-brozzler-boss.py
	PYTHONPATH=/home/nlevitt/workspace/ait5/ait5-ve34/lib/python3.4/site-packages /home/nlevitt/workspace/ait5/scripts/ait-brozzler-boss.py &>> /1/brzl/logs/ait-brozzler-boss.out &

	sleep 5

	echo $0: starting brozzler-workers
	for node in aidata{400,400-bu,401-bu} ; do
	    ssh -fn $node 'PYTHONPATH=/home/nlevitt/workspace/brozzler/brozzler-ve34/lib/python3.4/site-packages XAUTHORITY=/tmp/Xauthority.nlevitt DISPLAY=:1 /home/nlevitt/workspace/brozzler/brozzler-ve34/bin/brozzler-worker --rethinkdb-servers=wbgrp-svc036,wbgrp-svc020,wbgrp-svc035 --rethinkdb-db=archiveit_brozzler --max-browsers=10' &>> /1/brzl/logs/brozzler-worker-$node.out
	done

	echo $0: starting pywayback
	PYTHONPATH=/home/nlevitt/workspace/pygwb/pygwb-ve27/lib/python2.7/site-packages:/home/nlevitt/workspace/pygwb WAYBACK_CONFIG=/home/nlevitt/workspace/pygwb/gwb.yaml PATH=/home/nlevitt/workspace/pygwb/pygwb-ve27/bin:/usr/bin:/bin /home/nlevitt/workspace/pygwb/start-gwb.sh &>> /1/brzl/logs/pywayback.out &

	echo $0: starting ait5 partner webapp
	PYTHONPATH=/home/nlevitt/workspace/ait5/ait5-ve34/lib/python3.4/site-packages python3.4 /home/nlevitt/workspace/ait5/manage.py runserver_plus 0.0.0.0:8888 &>> /1/brzl/logs/ait5.out &

	echo $0: logs are in /1/brzl/logs
	echo $0: warcs are in /1/brzl/warcs
}

if [ $# != 1 ] ; then
	echo "Usage: $0 status|start|stop|restart|reset"
	exit 1
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
	echo "Usage: $0 status|start|stop|restart|reset"
	exit 1
fi

