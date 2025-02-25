#!/usr/bin/env python
"""
vagrant-brozzler-new-site.py - runs brozzler-new-site inside the vagrant vm to
queue a site for your vagrant brozzler deployment.

Fills in the --proxy option automatically. Some other options are passed
through.

This is a standalone script with no dependencies other than python, and should
work with python 2.7 or python 3.2+. The only reason it's not a bash script is
so we can use the argparse library.

Copyright (C) 2016 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import sys
import os
import argparse
import subprocess

try:
    from shlex import quote
except:
    from pipes import quote


def main(argv=[]):
    arg_parser = argparse.ArgumentParser(prog=os.path.basename(argv[0]))
    arg_parser.add_argument("seed", metavar="SEED", help="seed url")
    arg_parser.add_argument(
        "--time-limit",
        dest="time_limit",
        default=None,
        help="time limit in seconds for this site",
    )
    arg_parser.add_argument(
        "--ignore-robots",
        dest="ignore_robots",
        action="store_true",
        help="ignore robots.txt for this site",
    )
    arg_parser.add_argument(
        "--warcprox-meta",
        dest="warcprox_meta",
        help=(
            "Warcprox-Meta http request header to send with each request; "
            "must be a json blob, ignored unless warcprox features are "
            "enabled"
        ),
    )
    arg_parser.add_argument("-q", "--quiet", dest="quiet", action="store_true")
    arg_parser.add_argument("-v", "--verbose", dest="verbose", action="store_true")

    args = arg_parser.parse_args(args=argv[1:])

    options = []
    if args.time_limit:
        options.append("--time-limit=%s" % args.time_limit)
    if args.ignore_robots:
        options.append("--ignore-robots")
    if args.warcprox_meta:
        # I think this shell escaping is correct?
        options.append("--warcprox-meta=%s" % quote(args.warcprox_meta))
    if args.quiet:
        options.append("--quiet")
    if args.verbose:
        options.append("--verbose")

    # cd to path with Vagrantfile so "vagrant ssh" knows what to do
    os.chdir(os.path.dirname(__file__))

    cmd = (
        "/opt/brozzler-ve3/bin/python /opt/brozzler-ve3/bin/brozzler-new-site %s %s"
    ) % (" ".join(options), args.seed)
    subprocess.call(["vagrant", "ssh", "--", cmd])


if __name__ == "__main__":
    main(sys.argv)
