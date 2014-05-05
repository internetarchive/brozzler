# vim: set sw=4 et:

from json import dumps, load
from itertools import chain
import os, re
import logging
import time

class Behavior:
    logger = logging.getLogger('umbra.behaviors.Behavior')

    _behaviors = None
    _default_behavior_script = None

    @staticmethod
    def behaviors():
        if Behavior._behaviors is None:
            behaviors_directory = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.d'])
            behavior_files = chain(*[[os.path.join(dir, file) for file in files if file.endswith('.js') and file != 'default.js'] for dir, dirs, files in os.walk(behaviors_directory)])
            Behavior._behaviors = []
            for file_name in behavior_files:
                Behavior.logger.debug("reading behavior file {}".format(file_name))
                lines = open(file_name).readlines()
                pattern, script = lines[0][2:].strip(), ''.join(lines[1:])
                Behavior._behaviors.append({'url_regex': pattern, 'script': script, 'file': file_name})
                Behavior.logger.info("will run behaviors from {} to urls matching {}".format(file_name, pattern))

        return Behavior._behaviors

    @staticmethod
    def default_behavior_script():
        if Behavior._default_behavior_script is None:
            behaviors_directory = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.d'])
            file_name = os.path.join(behaviors_directory, 'default.js')
            Behavior.logger.debug("reading default behavior file {}".format(file_name))
            Behavior._default_behavior_script = open(file_name).read()
        return Behavior._default_behavior_script

    def __init__(self, url, websock, command_id):
        self.url = url
        self.websock = websock
        self.command_id = command_id

        self.script_finished = False
        self.waiting_result_msg_ids = []

    def start(self):
        self.notify_of_activity()

        script_started = False
        for behavior in Behavior.behaviors():
            if re.match(behavior['url_regex'], self.url):
                msg = dumps(dict(method="Runtime.evaluate", params={"expression": behavior['script']}, id=next(self.command_id)))
                self.logger.debug('sending message to {}: {}'.format(self.websock, msg))
                self.websock.send(msg)
                script_started = True
                break

        if not script_started:
            msg = dumps(dict(method="Runtime.evaluate", params={"expression": Behavior.default_behavior_script()}, id=next(self.command_id)))
            self.logger.debug('sending message to {}: {}'.format(self.websock, msg))
            self.websock.send(msg)

    def is_finished(self):
        msg_id = next(self.command_id)
        self.waiting_result_msg_ids.append(msg_id)
        msg = dumps(dict(method="Runtime.evaluate", params={"expression": "umbraBehaviorFinished()"}, id=msg_id))
        self.logger.debug('sending message to {}: {}'.format(self.websock, msg))
        self.websock.send(msg)

        return self.script_finished    # XXX and idle_time > behavior_specified_idle_timeout

    def is_waiting_on_result(self, msg_id):
        return msg_id in self.waiting_result_msg_ids

    def notify_of_result(self, chrome_message):
        # {'id': 59, 'result': {'result': {'type': 'boolean', 'value': True}, 'wasThrown': False}}
        self.waiting_result_msg_ids.remove(chrome_message['id'])
        if ('result' in chrome_message
                and not chrome_message['result']['wasThrown']
                and 'result' in chrome_message['result']
                and type(chrome_message['result']['result']['value']) == bool):
            self.script_finished = chrome_message['result']['result']['value']
        else:
            self.logger.error("chrome message doesn't look like a boolean result! {}".format(chrome_message))

    def notify_of_activity(self):
        self.last_activity = time.time()


