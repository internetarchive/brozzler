.. image:: https://travis-ci.org/internetarchive/brozzler.svg?branch=master
    :target: https://travis-ci.org/internetarchive/brozzler

.. |logo| image:: https://cdn.rawgit.com/internetarchive/brozzler/1.1b5/brozzler/webconsole/static/brozzler.svg
   :width: 60px

|logo| brozzler
===============
"browser" \| "crawler" = "brozzler"

Brozzler is a distributed web crawler (爬虫) that uses a real browser (Chrome or Chromium) to fetch pages and embedded URLs and to extract links. It employs `youtube-dl <https://github.com/rg3/youtube-dl>`_ to enhance media capture capabilities, warcprox to write content to Web ARChive (WARC) files, `rethinkdb <https://github.com/rethinkdb/rethinkdb>`_ to index captured URLs, a native dashboard for crawl job monitoring, and a customized Python Wayback interface for archival replay.

Requirements
------------

- Python 3.4 or later
- RethinkDB deployment
- Chromium or Google Chrome >= version 64

Note: The browser requires a graphical environment to run. When brozzler is run on a server, this may require deploying some additional infrastructure (typically X11; Xvfb does not support screenshots, however Xvnc4 from package vnc4server, does). The `vagrant configuration <vagrant/>`_ in the brozzler repository (still a work in progress) has an example setup. 

Getting Started
---------------

The easiest way to get started with brozzler for web archiving is with ``brozzler-easy``. Brozzler-easy runs brozzler-worker, warcprox, brozzler wayback, and brozzler-dashboard, configured to work with each other in a single process.

Mac instructions:

::

    # install and start rethinkdb
    brew install rethinkdb
    # no brew? try rethinkdb's installer: https://www.rethinkdb.com/docs/install/osx/
    rethinkdb &>>rethinkdb.log &

    # install brozzler with special dependencies pywb and warcprox
    pip install brozzler[easy]  # in a virtualenv if desired

    # queue a site to crawl
    brozzler-new-site http://example.com/

    # or a job
    brozzler-new-job job1.yml

    # start brozzler-easy
    brozzler-easy

At this point brozzler-easy will start archiving your site. Results will be immediately available for playback in pywb at http://localhost:8880/brozzler/.

*Brozzler-easy demonstrates the full brozzler archival crawling workflow, but
does not take advantage of brozzler's distributed nature.*

Installation and Usage
----------------------

To install brozzler only::

    pip install brozzler  # in a virtualenv if desired

Launch one or more workers::

    brozzler-worker --warcprox-auto

Submit jobs::

    brozzler-new-job myjob.yaml

Submit sites not tied to a job::

    brozzler-new-site --time-limit=600 http://example.com/

Job Configuration
-----------------

Brozzler jobs are defined using YAML files. Options may be specified either at the top-level or on individual seeds. At least one seed URL must be specified, however everything else is optional. For details, see `<job-conf.rst>`_.

::

    id: myjob
    time_limit: 60 # seconds
    proxy: 127.0.0.1:8000 # point at warcprox for archiving
    ignore_robots: false
    warcprox_meta: null
    metadata: {}
    seeds:
      - url: http://one.example.org/
      - url: http://two.example.org/
        time_limit: 30
      - url: http://three.example.org/
        time_limit: 10
        ignore_robots: true
        scope:
          surt: http://(org,example,

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

See ``brozzler-dashboard --help`` for configuration options.

Brozzler Wayback
----------------

Brozzler comes with a customized version of `pywb <https://github.com/ikreymer/pywb>`_, which supports using the rethinkdb "captures" table (populated by warcprox) as its index.

To use, first install dependencies.

::

    pip install brozzler[easy]

Write a configuration file pywb.yml.

::

    # 'archive_paths' should point to the output directory of warcprox
    archive_paths: warcs/  # pywb will fail without a trailing slash
    collections:
      brozzler:
        index_paths: !!python/object:brozzler.pywb.RethinkCDXSource
          db: brozzler
          table: captures
          servers:
          - localhost
    enable_auto_colls: false
    enable_cdx_api: true
    framed_replay: true
    port: 8880

Run pywb like so:

::

    $ PYWB_CONFIG_FILE=pywb.yml brozzler-wayback

Then browse http://localhost:8880/brozzler/.


Headless Chrome (experimental)
--------------------------------

`Headless Chromium <https://chromium.googlesource.com/chromium/src/+/master/headless/README.md>`_ is now available in stable Chrome releases for 64-bit Linux and may be used to run the browser without a visible window or X11.

To try this out, create a wrapper script like ~/bin/chrome-headless.sh:

::

    #!/bin/bash
    exec /opt/google/chrome/chrome --headless --disable-gpu "$@"

Run brozzler passing the path to the wrapper script as the ``--chrome-exe``
option:

::

    chmod +x ~/bin/chrome-headless.sh
    brozzler-worker --chrome-exe ~/bin/chrome-headless.sh

Beware: Chrome's headless mode is still very new and has `unresolved issues <https://bugs.chromium.org/p/chromium/issues/list?can=2&q=Proj%3DHeadless>`_. Its use with brozzler has not yet been extensively tested. You may experience hangs or crashes with some types of content. For the moment we recommend using Chrome's regular mode instead.

License
-------

Copyright 2015-2018 Internet Archive

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

