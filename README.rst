.. |logo| image:: https://cdn.rawgit.com/internetarchive/brozzler/1.1b12/brozzler/dashboard/static/brozzler.svg
   :width: 60px

|logo| brozzler
===============
"browser" \| "crawler" = "brozzler"

Brozzler is a distributed web crawler (爬虫) that uses a real browser (Chrome
or Chromium) to fetch pages and embedded URLs and to extract links. It employs
`yt-dlp <https://github.com/yt-dlp/yt-dlp>`_ (formerly youtube-dl) to enhance
media capture capabilities and `rethinkdb
<https://github.com/rethinkdb/rethinkdb>`_ to manage crawl state.

Brozzler is designed to work in conjunction with `warcprox
<https://github.com/internetarchive/warcprox>`_ for web archiving.

Requirements
------------

- Python 3.8 or later
- RethinkDB deployment
- Chromium or Google Chrome >= version 64

Note: The browser requires a graphical environment to run. When brozzler is run
on a server, this may require deploying some additional infrastructure,
typically X11. Xvnc4 and Xvfb are X11 variants that are suitable for use on a
server, because they don't display anything to a physical screen. The `vagrant
configuration <vagrant/>`_ in the brozzler repository has an example setup
using Xvnc4. (When last tested, chromium on Xvfb did not support screenshots,
so Xvnc4 is preferred at this time.)

Getting Started
---------------

The simplest way to get started with Brozzler is to use the ``brozzle-page``
command-line utility to pass in a single URL to crawl. You can also add a new
job defined with a YAML file (see `job-const.rst`) and start a local Brozzler
worker for a more complex crawl.

Mac instructions:

::

    # install and start rethinkdb
    brew install rethinkdb
    # no brew? try rethinkdb's installer: https://www.rethinkdb.com/docs/install/osx/
    rethinkdb &>>rethinkdb.log &

    # optional: create a virtualenv
    python -m venv .venv

    # install brozzler with rethinkdb extra
    pip install brozzler[rethinkdb]

    # crawl a single site
    brozzle-page https://example.org

    # or enqueue a job and start brozzler-worker
    brozzler-new-job job1.yml
    brozzler-worker

At this point Brozzler will start archiving your site.

*Running Brozzler locally in this manner demonstrates the full Brozzler
archival crawling workflow, but does not take advantage of Brozzler's
distributed nature.*

Installation and Usage
----------------------

To install brozzler only::

    pip install brozzler  # in a virtualenv if desired

Launch one or more workers: [*]_ ::

    brozzler-worker --warcprox-auto

Submit jobs::

    brozzler-new-job myjob.yaml

Submit sites not tied to a job::

    brozzler-new-site --time-limit=600 https://example.org/

.. [*] A note about ``--warcprox-auto``: this option tells brozzler to
   look for a healthy warcprox instance in the `rethinkdb service registry
   <https://github.com/internetarchive/doublethink#service-registry>`_. For
   this to work you need to have at least one instance of warcprox running,
   with the ``--rethinkdb-services-url`` option pointing to the same rethinkdb
   services table that brozzler is using. Using ``--warcprox-auto`` is
   recommended for clustered deployments.

Job Configuration
-----------------

Brozzler jobs are defined using YAML files. Options may be specified either at
the top-level or on individual seeds. At least one seed URL must be specified,
however everything else is optional. For details, see `<job-conf.rst>`_.

::

    id: myjob
    time_limit: 60 # seconds
    ignore_robots: false
    warcprox_meta: null
    metadata: {}
    seeds:
      - url: https://one.example.org/
      - url: https://two.example.org/
        time_limit: 30
      - url: https://three.example.org/
        time_limit: 10
        ignore_robots: true
        scope:
          surt: https://(org,example,

Brozzler Dashboard
------------------

Brozzler comes with a rudimentary web application for viewing crawl job status.
To install the brozzler with dependencies required to run this app, run

::

    pip install brozzler[dashboard]


To start the app, run

::

    brozzler-dashboard

At this point Brozzler Dashboard will be accessible at http://localhost:8000/.

.. image:: Brozzler-Dashboard.png

See ``brozzler-dashboard --help`` for configuration options.

Headless Chrome (experimental)
------------------------------

Brozzler is known to work nominally with Chrome/Chromium in headless mode, but
this has not yet been extensively tested.

License
-------

Copyright 2015-2024 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this software except in compliance with the License. You may
obtain a copy of the License at

::

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
