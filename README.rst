.. |logo| image:: https://cdn.rawgit.com/internetarchive/brozzler/1.1b5/brozzler/webconsole/static/brozzler.svg
   :width: 7%

brozzler |logo|
===============

"browser" \| "crawler" = "brozzler"

Brozzler is a distributed web crawler (爬虫) that uses a real browser (chrome
or chromium) to fetch pages and embedded urls and to extract links. It also
uses `youtube-dl <https://github.com/rg3/youtube-dl>`_ to enhance media
capture capabilities.

Brozzler is designed to work in conjunction with
`warcprox <https://github.com/internetarchive/warcprox>`_ for web
archiving.

Requirements
------------

- Python 3.4 or later
- RethinkDB deployment
- Chromium or Google Chrome browser

Worth noting is that the browser requires a graphical environment to run. You
already have this on your laptop, but on a server it will probably require
deploying some additional infrastructure (typically X11). The vagrant
configuration in the brozzler repository (still a work in progress) has an
example setup.

Getting Started
---------------

The easiest way to get started with brozzler for web archiving is with
``brozzler-easy``. Brozzler-easy runs brozzler-worker, warcprox,
`pywb <https://github.com/ikreymer/pywb>`_, and brozzler-webconsole, configured
to work with each other, in a single process.

Mac instructions:

::

    # install and start rethinkdb
    brew install rethinkdb
    rethinkdb &>>rethinkdb.log &

    # install brozzler with special dependencies pywb and warcprox
    pip install brozzler[easy]  # in a virtualenv if desired

    # queue a site to crawl
    brozzler-new-site http://example.com/

    # or a job
    brozzler-new-job job1.yml

    # start brozzler-easy
    brozzler-easy

At this point brozzler-easy will start brozzling your site. Results will be
immediately available for playback in pywb at http://localhost:8880/brozzler/.

*Brozzler-easy demonstrates the full brozzler archival crawling workflow, but
does not take advantage of brozzler's distributed nature.*

Installation and Usage
----------------------

To install brozzler only:

::

    pip install brozzler  # in a virtualenv if desired

Launch one or more workers:

::

    brozzler-worker

Submit jobs:

::

    brozzler-new-job myjob.yaml

Submit sites not tied to a job:

::

    brozzler-new-site --proxy=localhost:8000 --enable-warcprox-features \
        --time-limit=600 http://example.com/

Job Configuration
-----------------

Jobs are defined using yaml files. Options may be specified either at the
top-level or on individual seeds. A job id and at least one seed url
must be specified, everything else is optional. For details, see
`<job-conf.rst>`_.

::

    id: myjob
    time_limit: 60 # seconds
    proxy: 127.0.0.1:8000 # point at warcprox for archiving
    ignore_robots: false
    enable_warcprox_features: false
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

Brozzler Web Console
--------------------

Brozzler comes with a rudimentary web application for viewing crawl job status.
To install the brozzler with dependencies required to run this app, run

::

    pip install brozzler[webconsole]


To start the app, run

::

    brozzler-webconsole

See ``brozzler-webconsole --help`` for configuration options.

Headless Chromium
-----------------

`Headless Chromium <https://chromium.googlesource.com/chromium/src/+/master/headless/README.md>`_
may optionally be used instead of Chromium or Chrome to run Brozzler without
a visisble browser window or X11 server.  At the time of writing
``headless_shell`` is a separate Linux-only executable and must be compiled
from source.  Beware that compiling Chromium requires 10 GB of disk space,
several GB of RAM and patience.

Start by installing the dependencies listed in Chromium's `Linux-specific build
instructions <https://chromium.googlesource.com/chromium/src/+/master/docs/linux_build_instructions.md>`_.

Next install the build tools and fetch the source code:

::

    mkdir -p ~/chromium
    cd ~/chromium
    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git
    export $PATH=$PWD/depot_tools:$PATH
    fetch --no-history chromium --nosvn=True

Configure a headless release build (the debug builds are much larger):

::

    cd src
    mkdir -p out/release
    echo 'import("//build/args/headless.gn")' > out/release/args.gn
    echo 'is_debug = false' >> out/release/args.gn
    gn gen out/release

Run the compile:

::

    ninja -C out/release headless_shell

This will produce an ``out/release/headless_shell`` executable.  Unfortunately
this cannot be used with Brozzler as-is as the ``--window-size`` command-line
option expects a different syntax in Headless Chromium.  As a workaround create
a wrapper shell script ``headless_chromium.sh`` which replaces the misbehaving
option:

::

    #!/bin/bash
    exec ~/chromium/src/out/release/headless_shell "${@//--window-size=1100,900/--window-size=1100x900}"

Run brozzler passing the path to the wrapper script as the ``--chrome-exe``
option:

::

    chmod +x ~/bin/headless_chromium.sh
    brozzler-worker --chrome-exe ~/bin/headless_chromium.sh

The Pepper Flash plugin ``libpepflashplayer.so`` from an official Google Chrome
release may be used with Headless Chromium by adding this option to the wrapper
script:

::

    --register-pepper-plugins=/opt/google/chrome/PepperFlash/libpepflashplayer.so;application/x-shockwave-flash

License
-------

Copyright 2015-2016 Internet Archive

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

