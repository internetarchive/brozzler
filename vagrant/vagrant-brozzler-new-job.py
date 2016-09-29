#!/usr/bin/env python
'''
vagrant-brozzler-new-job.py - runs brozzler-new-job inside the vagrant vm to
queue a job for your vagrant brozzler deployment.

This is a standalone script with no dependencies other than python, and should
work with python 2.7 or python 3.2+. The only reason it's not a bash script is
so we can use the argparse library.
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

    with open(args.job_conf_file, 'rb') as f:
        yaml_bytes = f.read()
        subprocess.call(
                ['vagrant', 'ssh', '--', 'f=`mktemp` && cat > $f'],
                stdin=yaml_bytes)

    # cd to path with Vagrantfile so "vagrant ssh" knows what to do
    os.chdir(os.path.dirname(__file__))

if __name__ == '__main__':
    main(sys.argv)

## # cd to path with Vagrantfile so "vagrant ssh" knows what to do
## script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
## cd $script_dir
## 
## vagrant ssh -- \
##         PYTHONPATH=/home/vagrant/brozzler-ve34/lib/python3.4/site-packages \
##         /home/vagrant/brozzler-ve34/bin/python \
##         /home/vagrant/brozzler-ve34/bin/brozzler-new-job "$@"
