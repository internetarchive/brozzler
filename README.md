umbra
=====

Browser automation via chrome debug protocol

Install
======
Install via pip from this repo.

Run
=====
"umbra" script should be in bin/.
load_url.py takes urls as arguments and puts them onto a rabbitmq queue
dump_queue.py prints resources discovered by the browser and sent over the return queue.

On ubuntu, rabbitmq install with `sudo apt-get install rabbitmq-server` should automatically
be set up for these three scripts to function on localhost ( the default amqp url ).

