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

::

    # set up virtualenv if desired
    pip install brozzler

Brozzler also requires a rethinkdb deployment.

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

