#!/usr/bin/env python
from json import dumps, loads
import os,sys,argparse, urllib.request, urllib.error, urllib.parse
import websocket
import time
import uuid
import logging
import threading
from kombu import Connection, Exchange, Queue
logging.basicConfig(level=logging.INFO)
umbra_exchange = Exchange('umbra', 'direct', durable=True)
with Connection('amqp://guest:guest@localhost:5672//') as conn:
    producer = conn.Producer(serializer='json')
    producer.publish({'url': sys.argv[1]}, 'url', exchange=umbra_exchange)
        
