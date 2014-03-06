# vim: set sw=4 et:

from json import dumps, load
from time import sleep
from itertools import chain
import os, re
import logging

behaviors_directory = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.d'])
behavior_files = chain(*[[dir + os.path.sep + file for file in files] for dir, dirs, files  in os.walk(behaviors_directory)])
behaviors = []
for file_name in behavior_files:
    lines = open(file_name).readlines()
    pattern, script = lines[0][2:].strip(), ''.join(lines[1:])
    behaviors.append({'site' : pattern, 'script': script})

print(behaviors)
def execute(url, websock, command_id):
    logger = logging.getLogger('behaviors')
    print(behaviors)
    for behavior in behaviors:
        print("Comparing %s and %s" %(behavior['site'], url))
        if re.match(behavior['site'], url):
            msg = dumps(dict(method="Runtime.evaluate", params={"expression": behavior['script']}, id=next(command_id)))
            logger.debug('sending message to {}: {}'.format(websock, msg))
            websock.send(msg)
