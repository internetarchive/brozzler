#!/bin/bash

if [ `hostname -s` != wbgrp-svc107 ] ; then
    echo $0 expects to run on wbgrp-svc107
    exit 1
fi

_status() {
    something_running=1

    warcprox_pids=( $(pgrep -f /home/nlevitt/workspace/warcprox/warcprox-ve34/bin/warcprox) )
    worker_pids=( $(pgrep -f 'ssh .* docker run .* internetarchive/brozzler-worker .* brozzler-worker') )
    pywayback_pids=( $(pgrep -f /home/nlevitt/workspace/pygwb/pygwb-ve27/bin/gunicorn) )
    ait_brozzler_boss=( $(pgrep -f /home/nlevitt/workspace/ait5/scripts/ait-brozzler-boss.py) )
    ait5_pids=( $(pgrep -f 0.0.0.0:8888) )
    console_pids=( $(pgrep -f app=.*brozzler-webconsole.py) )

    pids="${warcprox_pids[*]} ${worker_pids[*]} ${pywayback_pids[*]} ${ait_brozzler_boss[*]} ${ait5_pids[*]} ${console_pids[*]}"
    if [ "$pids" != "     " ] ; then
        PS_FORMAT=user,pid,tid,ppid,pgid,sid,pri,nice,psr,%cpu,%mem,tty,stat,stime,time,args ps ww -H $pids
        echo
        something_running=0
    fi

    [ -z "${warcprox_pids[*]}" ] && echo "$0: warcprox is not running"
    [ -z "${worker_pids[*]}" ] && echo "$0: brozzler-workers are not running"
    [ -z "${pywayback_pids[*]}" ] && echo "$0: pywayback is not running"
    [ -z "${ait_brozzler_boss[*]}" ] && echo "$0: ait-brozzler-boss.py is not running"
    [ -z "${ait5_pids[*]}" ] && echo "$0: ait5 is not running"
    [ -z "${console_pids[*]}" ] && echo "$0: brozzler-webconsole.py is not running"

    return $something_running
}

_stop() {
    if _status ; then
        pkill -f /home/nlevitt/workspace/pygwb/pygwb-ve27/bin/gunicorn
        pkill -f /home/nlevitt/workspace/ait5/scripts/ait-brozzler-boss.py
        pkill -f 0.0.0.0:8888
        # pkill -f /home/nlevitt/workspace/brozzler/brozzler-ve34/bin/brozzler-worker
        for node in aidata{400,400-bu,401-bu} ; do
            container_id=$(ssh $node docker ps --filter=image=internetarchive/brozzler-worker --filter=status=running --format='{{.ID}}')
            [ -n "$container_id" ] && (set -x ; ssh $node docker stop --time=60 $container_id )
        done
        pkill -f app=.*brozzler-webconsole.py
    fi

    ssh wbgrp-svc111 pkill -f /home/nlevitt/workspace/warcprox/warcprox-ve34/bin/warcprox

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
    sudo umount /1/brzl/warcs
    mv -v /1/brzl /tmp/brzl.$tstamp
    mkdir -vp /1/brzl/{warcs,logs}
    # chgrp -v archiveit /1/brzl/warcs/ && chmod g+w /1/brzl/warcs
    ssh wbgrp-svc111 mv -v "/1/brzl/warcs /tmp/brzl-warcs.$tstamp && mkdir -vp /1/brzl/warcs"
    sudo -H -u archiveit sshfs wbgrp-svc111:/1/brzl/warcs /1/brzl/warcs -o nonempty,ro,allow_other
}

start_warcprox() {
    echo $0: starting warcprox
    ssh -fn wbgrp-svc111 'PYTHONPATH=/home/nlevitt/workspace/warcprox/warcprox-ve34/lib/python3.4/site-packages nice /home/nlevitt/workspace/warcprox/warcprox-ve34/bin/warcprox --dir=/1/brzl/warcs --rethinkdb-servers=wbgrp-svc020,wbgrp-svc035,wbgrp-svc036 --rethinkdb-db=archiveit_brozzler --rethinkdb-big-table --cacert=/1/brzl/warcprox-ca.pem --certs-dir=/1/brzl/certs --address=0.0.0.0 --base32 --gzip --rollover-idle-time=180 --kafka-broker-list=qa-archive-it.org:6092 --kafka-capture-feed-topic=ait-brozzler-captures' &>>/1/brzl/logs/warcprox.out &
}

start_brozzler_boss() {
    echo $0: starting ait-brozzler-boss.py
    venv=/home/nlevitt/workspace/ait5/ait5-ve34
    PYTHONPATH=$venv/lib/python3.4/site-packages $venv/bin/python /home/nlevitt/workspace/ait5/scripts/ait-brozzler-boss.py &>> /1/brzl/logs/ait-brozzler-boss.out &
}

start_brozzler_workers() {
    echo $0: starting brozzler-workers
    for node in aidata{400,400-bu,401,401-bu} ; do
        (
        set -x
        ssh $node "docker --version || curl -sSL https://get.docker.com/ | sh && sudo usermod -aG docker $USER"
        ssh $node 'docker build -t internetarchive/brozzler-worker /home/nlevitt/workspace/brozzler/docker'
        ssh -fn $node 'docker run --rm internetarchive/brozzler-worker /sbin/my_init -- setuser brozzler bash -c "DISPLAY=:1 brozzler-worker --rethinkdb-servers=wbgrp-svc036,wbgrp-svc020,wbgrp-svc035 --rethinkdb-db=archiveit_brozzler --max-browsers=10"'  &>> /1/brzl/logs/brozzler-worker-$node.out
        sleep 5
        )
    done
}

start_pywayback() {
    echo $0: starting pywayback
    PYTHONPATH=/home/nlevitt/workspace/pygwb/pygwb-ve27/lib/python2.7/site-packages WAYBACK_CONFIG=/home/nlevitt/workspace/pygwb/gwb.yaml PATH=/home/nlevitt/workspace/pygwb/pygwb-ve27/bin:/usr/bin:/bin /home/nlevitt/workspace/pygwb/start-gwb.sh &>> /1/brzl/logs/pywayback.out &
}

start_ait5() {
    echo $0: starting ait5 partner webapp
    PYTHONPATH=/home/nlevitt/workspace/ait5/ait5-ve34/lib/python3.4/site-packages python3.4 /home/nlevitt/workspace/ait5/manage.py runserver_plus 0.0.0.0:8888 &>> /1/brzl/logs/ait5.out &
}

start_brozzler_console() {
    echo $0: starting brozzler web console
    PYTHONPATH=/home/nlevitt/workspace/brozzler/webconsole/brozzler-webconsole-ve34/lib/python3.4/site-packages /home/nlevitt/workspace/brozzler/webconsole/brozzler-webconsole-ve34/bin/flask --debug --app=/home/nlevitt/workspace/brozzler/webconsole/brozzler-webconsole.py run --host=0.0.0.0 --port=8081 &>> /1/brzl/logs/brozzler-console.out &
}

start_dead() {
    warcprox_pids=( $(pgrep -f /home/nlevitt/workspace/warcprox/warcprox-ve34/bin/warcprox) )
    worker_pids=( $(pgrep -f 'ssh .* docker run .* internetarchive/brozzler-worker .* brozzler-worker') )
    pywayback_pids=( $(pgrep -f /home/nlevitt/workspace/pygwb/pygwb-ve27/bin/gunicorn) )
    ait_brozzler_boss=( $(pgrep -f /home/nlevitt/workspace/ait5/scripts/ait-brozzler-boss.py) )
    ait5_pids=( $(pgrep -f 0.0.0.0:8888) )
    console_pids=( $(pgrep -f app=.*brozzler-webconsole.py) )

    [ -z "${warcprox_pids[*]}" ] && start_warcprox
    [ -z "${worker_pids[*]}" ] && start_brozzler_workers
    [ -z "${pywayback_pids[*]}" ] && start_pywayback
    [ -z "${ait_brozzler_boss[*]}" ] && start_brozzler_boss
    [ -z "${ait5_pids[*]}" ] && start_ait5
    [ -z "${console_pids[*]}" ] && start_brozzler_console
}

_start() {
    if _status > /dev/null ; then
        echo "$0: can't start because something's still running"
        exit 1
    fi

    set -e
    start_warcprox
    sleep 5
    start_brozzler_boss
    sleep 5
    start_brozzler_workers
    start_pywayback
    start_ait5
    start_brozzler_console

    echo $0: logs are in /1/brzl/logs
    echo $0: warcs are in /1/brzl/warcs
}

usage() {
    echo "Usage: $0 status|start|stop|restart|reset|start-dead"
}

if [ $# != 1 ] ; then
    usage
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
elif [ $1 = 'start-dead' ] ; then
    start_dead
else
    usage
    exit 1
fi

