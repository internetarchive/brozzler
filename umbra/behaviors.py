from json import dumps, load
from time import sleep
import os, re

behaviors_file = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.json'])
def execute(url, ws, command_id):
    sleep(5)
    with open(behaviors_file) as js:
        behaviors = load(js)
        for behavior in behaviors:
            if re.match(behavior['site'], url):
                for script in behavior['scripts']:
                    ws.send(dumps(dict(method="Runtime.evaluate", params={"expression": script}, id=next(command_id))))
