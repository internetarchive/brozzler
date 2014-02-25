#!/usr/bin/env python
# vim: set sw=4 et:
from json import dumps, loads
import os,sys,argparse, urllib.request, urllib.error, urllib.parse
import websocket
import time
import uuid
import logging
import threading
from kombu import Connection, Exchange, Queue

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
        format='%(asctime)s %(process)d %(levelname)s %(threadName)s %(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s')

arg_parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]),
        description='load_url.py - send url to umbra via amqp',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
arg_parser.add_argument('-u', '--url', dest='amqp_url', default='amqp://guest:guest@localhost:5672//',
        help='URL identifying the amqp server to talk to')
arg_parser.add_argument('-i', '--client-id', dest='client_id', default='load_url.0',
        help='client id - included in the json payload with each url; umbra uses this value as the routing key to send requests back to')
arg_parser.add_argument('urls', metavar='URL', nargs='+', help='URLs to send to umbra')
args = arg_parser.parse_args(args=sys.argv[1:])

umbra_exchange = Exchange('umbra', 'direct', durable=True)
with Connection(args.amqp_url) as conn:
    producer = conn.Producer(serializer='json')
    for url in args.urls:
        producer.publish({'url': url, 'metadata': {}, 'clientId': args.client_id}, 'url', exchange=umbra_exchange)
        
