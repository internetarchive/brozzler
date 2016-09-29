brozzler job configuration
==========================

Jobs are defined using yaml files. Options may be specified either at the
top-level or on individual seeds. A job id and at least one seed url
must be specified, everything else is optional.

an example
----------

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
---------------------

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
