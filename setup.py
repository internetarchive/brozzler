import setuptools 

setuptools.setup(name='umbra',
        version='0.1',
        description='Google Chrome remote control interface',
        url='https://github.com/internetarchive/umbra',
        author='Eldon Stegall',
        author_email='eldon@archive.org',
        long_description=open('README.md').read(),
        license='Apache License 2.0',
        packages=['umbra'],
        package_data={'umbra':['behaviors.d/*.js']},
        install_requires=['kombu', 'websocket-client-py3','argparse'],
        scripts=['bin/umbra', 'bin/load_url.py', 'bin/dump_queue.py'],
        zip_safe=False,
        classifiers=[
            'Development Status :: 3 - Alpha Development Status',
            'Environment :: Console',
            'License :: OSI Approved :: Apache Software License',
            'Programming Language :: Python :: 3.3',
            'Topic :: System :: Archiving',
        ])
