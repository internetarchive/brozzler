# vim: set sw=4 et:

from json import dumps, load
from time import sleep
import os, re
import logging

behaviors_file = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.json'])
def execute(url, websock, command_id):
    logger = logging.getLogger('behaviors')
    with open(behaviors_file) as js:
        behaviors = load(js)
        for behavior in behaviors:
            if re.match(behavior['site'], url):
                for script in behavior['scripts']:
                    msg = dumps(dict(method="Runtime.evaluate", params={"expression": script}, id=next(command_id)))
                    logger.debug('sending message to {}: {}'.format(websock, msg))
                    websock.send(msg)
