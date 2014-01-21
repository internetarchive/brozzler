#!/usr/bin/env python
from json import dumps, loads
import os,sys,argparse, urllib2
import websocket
import thread
import time

def on_message(ws, message):
    message = loads(message)
    if "method" in message.keys() and message["method"] == "Network.requestWillBeSent":
        print message
        

def on_error(ws, error):
    print error

def on_close(ws):
    print "### closed ###"

def on_open(ws):
    cmd = {}
    cmd['id'] = 1001
    cmd['method'] = "Network.enable"
    ws.send(dumps(cmd))
    cmd['id'] = 1002
    cmd['method'] = "Runtime.evaluate"
    cmd["params"] = { "expression" : "document.location = 'http://archive.org'"}
    ws.send(dumps(cmd))

class Chrome():
    def __init__(self, port):
        self.port = port

    def __enter__(self):
        import psutil, subprocess
        self.chrome_process = subprocess.Popen(["google-chrome", "--remote-debugging-port=%s" % self.port])
        start = time.time()
        open_debug_port = lambda conn: conn.laddr[1] == int(self.port)
        chrome_ps_wrapper = psutil.Process(self.chrome_process.pid)
        while time.time() - start < 10 and len(filter(open_debug_port, chrome_ps_wrapper.get_connections())) == 0:
            time.sleep(1)
        if len(filter(open_debug_port, chrome_ps_wrapper.get_connections())) == 0:
            self.chrome_process.kill()
            raise Exception("Chrome failed to listen on the debug port in time!")

    def __exit__(self, *args):
        print "Killing"
        self.chrome_process.kill() 

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]),
            description='umbra - Browser automation tool',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    arg_parser.add_argument('-p', '--port', dest='port', default='9222',
            help='Port to have invoked chrome listen on for debugging connections')
    args = arg_parser.parse_args(args=sys.argv[1:])
    with Chrome(args.port):
        debug_info = loads(urllib2.urlopen("http://localhost:%s/json" % args.port).read())
        url = debug_info[0]['webSocketDebuggerUrl']
        ws = websocket.WebSocketApp(url,
            on_message = on_message,
            on_error = on_error,
            on_close = on_close)
        ws.on_open = on_open
        ws.run_forever()

