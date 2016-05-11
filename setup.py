#
# setup.py - brozzler setup script
#
# Copyright (C) 2014-2016 Internet Archive
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import setuptools
import glob

setuptools.setup(name='brozzler',
        version='1.1.dev10',
        description='Distributed web crawling with browsers',
        url='https://github.com/nlevitt/brozzler',
        author='Noah Levitt',
        author_email='nlevitt@archive.org',
        long_description=open('README.rst', encoding='UTF-8').read(),
        license='Apache License 2.0',
        packages=['brozzler'],
        package_data={'brozzler': ['behaviors.d/*.js*', 'behaviors.yaml']},
        scripts=glob.glob('bin/*'),
        install_requires=[
            'PyYAML',
            'youtube-dl',
            'reppy',
            'requests',
            'websocket-client',
            'pillow',
            'surt>=0.3b2',
            'rethinkstuff',
            'rethinkdb>=2.3,<2.4',
            'psutil',
            ],
        zip_safe=False,
        classifiers=[
            'Development Status :: 3 - Alpha',
            'Environment :: Console',
            'License :: OSI Approved :: Apache Software License',
            'Programming Language :: Python :: 3.4',
            'Topic :: Internet :: WWW/HTTP',
            'Topic :: System :: Archiving',
        ])
