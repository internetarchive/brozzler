brozzler job configuration
**************************

Jobs are defined using yaml files. Options may be specified either at the
top-level or on individual seeds. A job id and at least one seed url
must be specified, everything else is optional.

an example
==========

::

    id: myjob
    time_limit: 60 # seconds
    proxy: 127.0.0.1:8000 # point at warcprox for archiving
    ignore_robots: false
    enable_warcprox_features: false
    warcprox_meta:
      warc-prefix: job1
      stats:
        buckets:
        - job1-stats
    metadata: {}
    seeds:
    - url: http://one.example.org/
      warcprox_meta:
        warc-prefix: job1-seed1
        stats:
          buckets:
          - job1-seed1-stats
    - url: http://two.example.org/
      time_limit: 30
    - url: http://three.example.org/
      time_limit: 10
      ignore_robots: true
      scope:
        surt: http://(org,example,

how inheritance works
=====================

Most of the available options apply to seeds. Such options can also be
specified at the top level, in which case the seeds inherit the options. If
an option is specified both at the top level and at the level of an individual
seed, the results are merged with the seed-level value taking precedence in
case of conflicts. It's probably easiest to make sense of this by way of an
example.

In the example yaml above, ``warcprox_meta`` is specified at the top level and
at the seed level for the seed http://one.example.org/. At the top level we
have::

  warcprox_meta:
    warc-prefix: job1
    stats:
      buckets:
      - job1-stats

At the seed level we have::

    warcprox_meta:
      warc-prefix: job1-seed1
      stats:
        buckets:
        - job1-seed1-stats

The merged configuration as applied to the seed http://one.example.org/ will
be::

    warcprox_meta:
      warc-prefix: job1-seed1
      stats:
        buckets:
        - job1-stats
        - job1-seed1-stats

Notice that:

- There is a collision on ``warc-prefix`` and the seed-level value wins.
- Since ``buckets`` is a list, the merged result includes all the values from
  both the top level and the seed level.

settings reference
==================

id
--
+-----------+--------+----------+---------+
| scope     | type   | required | default |
+===========+========+==========+=========+
| top-level | string | yes?     | *n/a*   |
+-----------+--------+----------+---------+
An arbitrary identifier for this job. Must be unique across this deployment of
brozzler.

seeds
-----
+-----------+------------------------+----------+---------+
| scope     | type                   | required | default |
+===========+========================+==========+=========+
| top-level | list (of dictionaries) | yes      | *n/a*   |
+-----------+------------------------+----------+---------+
List of seeds. Each item in the list is a dictionary (associative array) which
defines the seed. It must specify ``url`` (see below) and can additionally
specify any of the settings of scope *seed-level*.

url
---
+------------+--------+----------+---------+
| scope      | type   | required | default |
+============+========+==========+=========+
| seed-level | string | yes      | *n/a*   |
+------------+--------+----------+---------+
The seed url.

time_limit
----------
+-----------------------+--------+----------+---------+
| scope                 | type   | required | default |
+=======================+========+==========+=========+
| seed-level, top-level | number | no       | *none*  |
+-----------------------+--------+----------+---------+
Time limit in seconds. If not specified, there no time limit. Time limit is
enforced at the seed level. If a time limit is specified at the top level, it
is inherited by each seed as described above, and enforced individually on each
seed.

proxy
-----
+-----------------------+--------+----------+---------+
| scope                 | type   | required | default |
+=======================+========+==========+=========+
| seed-level, top-level | string | no       | *none*  |
+-----------------------+--------+----------+---------+
HTTP proxy, with the format ``host:port``. Typically configured to point to
warcprox for archival crawling.

enable_warcprox_features
------------------------
+-----------------------+---------+----------+---------+
| scope                 | type    | required | default |
+=======================+=========+==========+=========+
| seed-level, top-level | boolean | no       | false   |
+-----------------------+---------+----------+---------+
If true for a given seed, and the seed is configured to use a proxy, enables
special features that assume the proxy is an instance of warcprox. As of this
writing, the special features that are enabled are:

- sending screenshots and thumbnails to warcprox using a WARCPROX_WRITE_RECORD
  request
- sending youtube-dl metadata json to warcprox using a WARCPROX_WRITE_RECORD
  request

See the warcprox docs for information on the WARCPROX_WRITE_RECORD method (XXX
not yet written).

*Note that if* ``warcprox_meta`` *and* ``proxy`` *are configured, the
Warcprox-Meta header will be sent even if* ``enable_warcprox_features`` *is not
set.*

ignore_robots
-------------
+-----------------------+---------+----------+---------+
| scope                 | type    | required | default |
+=======================+=========+==========+=========+
| seed-level, top-level | boolean | no       | false   |
+-----------------------+---------+----------+---------+
If set to ``true``, brozzler will happily crawl pages that would otherwise be
blocked by robots.txt rules.

warcprox_meta
-------------
+-----------------------+------------+----------+---------+
| scope                 | type       | required | default |
+=======================+============+==========+=========+
| seed-level, top-level | dictionary | no       | false   |
+-----------------------+------------+----------+---------+
Specifies the Warcprox-Meta header to send with every request, if ``proxy`` is
configured. The value of the Warcprox-Meta header is a json blob. It is used to
pass settings and information to warcprox. Warcprox does not forward the header
on to the remote site. See the warcprox docs for more information (XXX not yet
written).

Brozzler takes the configured value of ``warcprox_meta``, converts it to
json and populates the Warcprox-Meta header with that value. For example::

    warcprox_meta:
      warc-prefix: job1-seed1
      stats:
        buckets:
        - job1-stats
        - job1-seed1-stats

becomes::

    Warcprox-Meta: {"warc-prefix":"job1-seed1","stats":{"buckets":["job1-stats","job1-seed1-stats"]}}

scope
-----
+-----------------------+------------+----------+---------+
| scope                 | type       | required | default |
+=======================+============+==========+=========+
| seed-level, top-level | dictionary | no       | false   |
+-----------------------+------------+----------+---------+
Scope rules. *TODO*