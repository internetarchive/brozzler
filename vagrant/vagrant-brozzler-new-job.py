#!/usr/bin/env python
'''
vagrant-brozzler-new-job.py - runs brozzler-new-job inside the vagrant vm to
queue a job for your vagrant brozzler deployment.

This is a standalone script with no dependencies other than python, and should
work with python 2.7 or python 3.2+. The only reason it's not a bash script is
so we can use the argparse library.

Copyright (C) 2016-2019 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

import sys
import os
import argparse
import subprocess

def main(argv=[]):
    arg_parser = argparse.ArgumentParser(prog=os.path.basename(argv[0]))
    arg_parser.add_argument(
            'job_conf_file', metavar='JOB_CONF_FILE',
            help='brozzler job configuration file in yaml')
    args = arg_parser.parse_args(args=argv[1:])
    args.job_conf_file = os.path.realpath(args.job_conf_file)

    # cd to path with Vagrantfile so "vagrant ssh" knows what to do
    os.chdir(os.path.realpath(os.path.dirname(__file__)))

    with open(args.job_conf_file, 'rb') as f:
        subprocess.call([
            'vagrant', 'ssh', '--',
            'f=`mktemp` && cat > $f && '
            '/opt/brozzler-ve3/bin/python '
            '/opt/brozzler-ve3/bin/brozzler-new-job $f'],
            stdin=f)

if __name__ == '__main__':
    main(sys.argv)
