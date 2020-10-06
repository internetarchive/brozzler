Single-VM Vagrant Brozzler Deployment
-------------------------------------

This is a vagrant + ansible configuration for a single-vm deployment of
brozzler and warcprox with dependencies (notably rethinkdb).

The idea is for this to be a quick way for people to get up and running with a
deployment resembling a real distributed deployment, and to offer a starting
configuration for people to adapt to their clusters.

And equally important, as a harness for integration tests.

You'll need vagrant installed.
https://www.vagrantup.com/docs/installation/
Then run:

::

    my-laptop$ vagrant up

Currently to start a crawl you first need to ssh to the vagrant vm and activate
the brozzler virtualenv.

::

    my-laptop$ vagrant ssh
    vagrant@brzl:~$ source /opt/brozzler-ve3/bin/activate
    (brozzler-ve3)vagrant@brzl:~$

Then you can run brozzler-new-site:

::

    (brozzler-ve3)vagrant@brzl:~$ brozzler-new-site http://example.com/


Or brozzler-new-job:

::

    (brozzler-ve3)vagrant@brzl:~$ cat >job1.yml <<EOF
    id: job1
    seeds:
    - url: https://example.org/
    EOF
    (brozzler-ve3)vagrant@brzl:~$ brozzler-new-job job1.yml

WARC files will appear in ./warcs and brozzler, warcprox and rethinkdb logs in
./logs (via vagrant folders syncing).

You can also look at the rethinkdb console by opening http://localhost:8080 in
your browser after opening an ssh tunnel like so:

::

    my-laptop$ vagrant ssh -- -fN -Llocalhost:8080:localhost:8080

