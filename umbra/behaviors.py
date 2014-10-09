# vim: set sw=4 et:

import json
import itertools
import os
import re
import logging
import time
import sys

class Behavior:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    _behaviors = None
    _default_behavior = None

    @staticmethod
    def behaviors():
        if Behavior._behaviors is None:
            behaviors_directory = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.d'])
            behavior_files = itertools.chain(*[[os.path.join(dir, file) for file in files if file.endswith('.js') and file != 'default.js'] for dir, dirs, files in os.walk(behaviors_directory)])
            Behavior._behaviors = []
            for file_name in behavior_files:
                Behavior.logger.debug("reading behavior file {}".format(file_name))
                script = open(file_name, encoding='utf-8').read()
                first_line = script[:script.find('\n')]
                behavior = json.loads(first_line[2:].strip())
                behavior['script'] = script
                behavior['file'] = file_name
                Behavior._behaviors.append(behavior)
                Behavior.logger.info("will run behaviors from {} on urls matching {}".format(file_name, behavior['url_regex']))

        return Behavior._behaviors

    @staticmethod
    def default_behavior():
        if Behavior._default_behavior is None:
            behaviors_directory = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.d'])
            file_name = os.path.join(behaviors_directory, 'default.js')
            Behavior.logger.debug("reading default behavior file {}".format(file_name))
            script = open(file_name, encoding='utf-8').read()
            first_line = script[:script.find('\n')]
            behavior = json.loads(first_line[2:].strip())
            behavior['script'] = script
            behavior['file'] = file_name
            Behavior._default_behavior = behavior
        return Behavior._default_behavior

    def __init__(self, url, umbra_worker):
        self.url = url
        self.umbra_worker = umbra_worker

        self.script_finished = False
        self.waiting_result_msg_ids = []
        self.active_behavior = None
        self.last_activity = time.time()

    def start(self):
        for behavior in Behavior.behaviors():
            if re.match(behavior['url_regex'], self.url):
                self.active_behavior = behavior
                break

        if self.active_behavior is None:
            self.active_behavior = Behavior.default_behavior()

        self.umbra_worker.send_to_chrome(method="Runtime.evaluate", params={"expression": self.active_behavior['script']})
        self.notify_of_activity()

    def is_finished(self):
        msg_id = self.umbra_worker.send_to_chrome(method="Runtime.evaluate",
                suppress_logging=True, params={"expression":"umbraBehaviorFinished()"})
        self.waiting_result_msg_ids.append(msg_id)

        request_idle_timeout_sec = 30
        if self.active_behavior and 'request_idle_timeout_sec' in self.active_behavior:
            request_idle_timeout_sec = self.active_behavior['request_idle_timeout_sec']
        idle_time = time.time() - self.last_activity

        return self.script_finished and idle_time > request_idle_timeout_sec

    def is_waiting_on_result(self, msg_id):
        return msg_id in self.waiting_result_msg_ids

    def notify_of_result(self, chrome_message):
        # {'id': 59, 'result': {'result': {'type': 'boolean', 'value': True}, 'wasThrown': False}}
        # {'id': 59, 'result': {'result': {'type': 'boolean', 'value': False}}
        self.waiting_result_msg_ids.remove(chrome_message['id'])
        if ('result' in chrome_message
                and not ('wasThrown' in chrome_message['result'] and chrome_message['result']['wasThrown'])
                and 'result' in chrome_message['result']
                and type(chrome_message['result']['result']['value']) == bool):
            self.script_finished = chrome_message['result']['result']['value']
        else:
            self.logger.error("chrome message doesn't look like a boolean result! {}".format(chrome_message))

    def notify_of_activity(self):
        self.last_activity = time.time()

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
            format='%(asctime)s %(process)d %(levelname)s %(threadName)s %(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s')
    logger = logging.getLogger('umbra.behaviors')
    logger.info("custom behaviors: {}".format(Behavior.behaviors()))
    logger.info("default behavior: {}".format(Behavior.default_behavior()))


