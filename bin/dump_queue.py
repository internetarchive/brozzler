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
requests_queue = Queue('requests', exchange=umbra_exchange)
def print_and_ack(body, message):
    print(body)
    message.ack()

with Connection('amqp://guest:guest@localhost:5672//') as conn:
    with conn.Consumer(requests_queue, callbacks=[print_and_ack]) as consumer:
        while True:
            conn.drain_events()
