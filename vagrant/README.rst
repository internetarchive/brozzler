Single-VM Vagrant Brozzler Deployment
-------------------------------------

This is a work in progress. Vagrant + ansible configuration for a single-vm
deployment of brozzler and warcprox with dependencies (notably rethinkdb).

The idea is for this to be a quick way for people to get up and running with a
deployment resembling a real distributed deployment, and to offer a starting
configuration for people to adapt to their clusters.

And equally important, as a harness for integration tests. (As of now brozzler
itself has no automated tests!)

You'll need vagrant installed.
https://www.vagrantup.com/docs/installation/
Then run:

::

    my-laptop$ vagrant up

Currently to start a crawl you first need to ssh to the vagrant vm and activate
the brozzler virtualenv.

::

    my-laptop$ vagrant ssh
    vagrant@brozzler-easy:~$ source /opt/brozzler-ve34/bin/activate
    (brozzler-ve34)vagrant@brozzler-easy:~$

Then you can run brozzler-new-site:

::

    (brozzler-ve34)vagrant@brozzler-easy:~$ brozzler-new-site http://example.com/


Or brozzler-new-job (make sure to set the proxy to localhost:8000):

::

    (brozzler-ve34)vagrant@brozzler-easy:~$ cat > job1.yml <<EOF
    id: job1
    proxy: localhost:8000 # point at warcprox for archiving
    seeds:
      - url: https://example.org/
    EOF
    (brozzler-ve34)vagrant@brozzler-easy:~$ brozzler-new-job job1.yml

WARC files will appear in ./warcs and brozzler, warcprox and rethinkdb logs in
./logs (via vagrant folders syncing).

You can also look at the rethinkdb console by opening http://localhost:8080 in
your browser after opening an ssh tunnel like so:

::

    my-laptop$ vagrant ssh -- -fN -Llocalhost:8080:localhost:8080

