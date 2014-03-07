# vim: set sw=4 et:

from json import dumps, load
from time import sleep
from itertools import chain
import os, re
import logging

logger = logging.getLogger('behaviors')
behaviors_directory = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.d'])
behavior_files = chain(*[[os.path.join(dir, file) for file in files if re.match('^[^.].*\.js$', file)] for dir, dirs, files in os.walk(behaviors_directory)])
behaviors = []
for file_name in behavior_files:
    logger.debug("reading behavior file {}".format(file_name))
    lines = open(file_name).readlines()
    pattern, script = lines[0][2:].strip(), ''.join(lines[1:])
    behaviors.append({'url_regex': pattern, 'script': script, 'file': file_name})
    logger.info("will run behaviors from {} to urls matching {}".format(file_name, pattern))

def execute(url, websock, command_id):
    for behavior in behaviors:
        if re.match(behavior['url_regex'], url):
            msg = dumps(dict(method="Runtime.evaluate", params={"expression": behavior['script']}, id=next(command_id)))
            logger.debug('sending message to {}: {}'.format(websock, msg))
            websock.send(msg)
