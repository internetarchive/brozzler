.. |logo| image:: https://cdn.rawgit.com/nlevitt/brozzler/d1158ab2242815b28fe7bb066042b5b5982e4627/webconsole/static/brozzler.svg
   :width: 7%

brozzler |logo|
===============

"browser" \| "crawler" = "brozzler"

Brozzler is a distributed web crawler (爬虫) that uses a real browser
(chrome or chromium) to fetch pages and embedded urls and to extract
links. It also uses `youtube-dl <https://github.com/rg3/youtube-dl>`__
to enhance media capture capabilities.

It is forked from https://github.com/internetarchive/umbra.

Brozzler is designed to work in conjunction with
`warcprox <https://github.com/internetarchive/warcprox>`__ for web
archiving.

Installation
------------

Brozzler requires python 3.4 or later.

::

    # set up virtualenv if desired
    pip install brozzler

Brozzler also requires a rethinkdb deployment.

Usage
-----

Launch one or more workers:

::

    brozzler-worker -e chromium

Submit jobs:

::

    brozzler-new-job myjob.yaml

Job Configuration
-----------------

Jobs are defined using yaml files. Options may be specified either at the
top-level or on individual seeds. A job id and at least one seed url
must be specified, everything else is optional.

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

Submit a Site to Crawl Without Configuring a Job
------------------------------------------------

::

    brozzler-new-site --proxy=localhost:8000 --enable-warcprox-features \
        --time-limit=600 http://example.com/

Brozzler Web Console
--------------------

Brozzler comes with a rudimentary web application for viewing crawl job status.
To install the brozzler with dependencies required to run this app, run

::

    pip install brozzler[webconsole]


To start the app, run

::

    brozzler-webconsole


XXX configuration stuff

Fonts (for decent screenshots)
------------------------------

On ubuntu 14.04 trusty I installed these packages:

xfonts-base ttf-mscorefonts-installer fonts-arphic-bkai00mp
fonts-arphic-bsmi00lp fonts-arphic-gbsn00lp fonts-arphic-gkai00mp
fonts-arphic-ukai fonts-farsiweb fonts-nafees fonts-sil-abyssinica
fonts-sil-ezra fonts-sil-padauk fonts-unfonts-extra fonts-unfonts-core
ttf-indic-fonts fonts-thai-tlwg fonts-lklug-sinhala

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

