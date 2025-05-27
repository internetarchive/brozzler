#!/usr/bin/env python
"""
setup.py - brozzler setup script

Copyright (C) 2014-2025 Internet Archive

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

import os

import setuptools


def find_package_data(package):
    pkg_data = []
    depth = len(package.split("."))
    path = os.path.join(*package.split("."))
    for dirpath, dirnames, filenames in os.walk(path):
        if not os.path.exists(os.path.join(dirpath, "__init__.py")):
            relpath = os.path.join(*dirpath.split(os.sep)[depth:])
            pkg_data.extend(os.path.join(relpath, f) for f in filenames)
    return pkg_data


setuptools.setup(
    name="brozzler",
    version="1.6.13a0",
    description="Distributed web crawling with browsers",
    url="https://github.com/internetarchive/brozzler",
    author="Noah Levitt",
    author_email="nlevitt@archive.org",
    long_description=open("README.rst", mode="rb").read().decode("UTF-8"),
    license="Apache License 2.0",
    packages=["brozzler", "brozzler.dashboard"],
    package_data={
        "brozzler": ["js-templates/*.js*", "behaviors.yaml", "job_schema.yaml"],
        "brozzler.dashboard": find_package_data("brozzler.dashboard"),
    },
    entry_points={
        "console_scripts": [
            "brozzle-page=brozzler.cli:brozzle_page",
            "brozzler-new-job=brozzler.cli:brozzler_new_job",
            "brozzler-new-site=brozzler.cli:brozzler_new_site",
            "brozzler-worker=brozzler.cli:brozzler_worker",
            "brozzler-ensure-tables=brozzler.cli:brozzler_ensure_tables",
            "brozzler-list-captures=brozzler.cli:brozzler_list_captures",
            "brozzler-list-jobs=brozzler.cli:brozzler_list_jobs",
            "brozzler-list-sites=brozzler.cli:brozzler_list_sites",
            "brozzler-list-pages=brozzler.cli:brozzler_list_pages",
            "brozzler-stop-crawl=brozzler.cli:brozzler_stop_crawl",
            "brozzler-purge=brozzler.cli:brozzler_purge",
            "brozzler-dashboard=brozzler.dashboard:main",
            "brozzler-easy=brozzler.easy:main",
            "brozzler-wayback=brozzler.pywb:main",
        ],
    },
    zip_safe=False,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.8",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: System :: Archiving",
    ],
)
