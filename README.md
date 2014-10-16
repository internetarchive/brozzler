umbra
=====
Umbra is a browser automation tool, developed for the web archiving service
https://archive-it.org/. 

Umbra receives urls via AMQP. It opens them in the chrome or chromium browser,
with which it communicates using the chrome remote debug protocol (see
https://developer.chrome.com/devtools/docs/debugger-protocol). It runs
javascript behaviors to simulate user interaction with the page. It publishes
information about the the urls requested by the browser back to AMQP. The
format of the incoming and outgoing AMQP messages is described in `pydoc
umbra.controller`.

Umbra can be used with the Heritrix web crawler, using these heritrix modules:
* [AMQPUrlReceiver](https://github.com/internetarchive/heritrix3/blob/master/contrib/src/main/java/org/archive/crawler/frontier/AMQPUrlReceiver.java)
* [AMQPPublishProcessor](https://github.com/internetarchive/heritrix3/blob/master/contrib/src/main/java/org/archive/modules/AMQPPublishProcessor.java)

Install
------
Install via pip from this repo, e.g.

    pip install git+https://github.com/internetarchive/umbra.git

Umbra requires an AMQP messaging service like RabbitMQ. On Ubuntu,
`sudo apt-get install rabbitmq-server` will install and start RabbitMQ
at amqp://guest:guest@localhost:5672/%2f, which the default AMQP url for umbra.

Run
---
The command `umbra` will start umbra with default configuration. `umbra --help`
describes all command line options.

Umbra also comes with these utilities:
* browse-url - open urls in chrome/chromium and run behaviors (without involving AMQP)
* queue-url - send url to umbra via AMQP
* drain-queue - consume messages from AMQP queue

License
-------

Copyright 2014 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this software except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

