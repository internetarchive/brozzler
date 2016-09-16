#!/bin/bash
#
# vagrant-brozzler-new-site.sh - run brozzler-new-site inside the vagrant vm to
# queue a job for your vagrant brozzler deployment
#

# cd to path with Vagrantfile so "vagrant ssh" knows what to do
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd $script_dir

vagrant ssh -- \
        PYTHONPATH=/home/vagrant/brozzler-ve34/lib/python3.4/site-packages \
        /home/vagrant/brozzler-ve34/bin/python \
        /home/vagrant/brozzler-ve34/bin/brozzler-new-site "$@"
