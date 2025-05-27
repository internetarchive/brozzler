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
    description="Distributed web crawling with browsers",
    url="https://github.com/internetarchive/brozzler",
    author="Noah Levitt",
    author_email="nlevitt@archive.org",
    long_description=open("README.rst", mode="rb").read().decode("UTF-8"),
    packages=["brozzler", "brozzler.dashboard"],
    package_data={
        "brozzler": ["js-templates/*.js*", "behaviors.yaml", "job_schema.yaml"],
        "brozzler.dashboard": find_package_data("brozzler.dashboard"),
    },
    zip_safe=False,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Programming Language :: Python :: 3.8",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: System :: Archiving",
    ],
)
