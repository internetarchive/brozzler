import setuptools 

setuptools.setup(name='umbra',
        version='0.1',
        description='Google Chrome remote control interface',
        url='https://github.com/eldondev/umbra',
        author='Eldon Stegall',
        author_email='eldon@archive.org',
        long_description=open('README.md').read(),
        license='GPL',
        packages=['umbra'],
        install_requires=['kombu', 'websocket-client-py3','psutil','argparse'],
        scripts=['bin/umbra'],
        zip_safe=False,
        classifiers=[
            'Development Status :: 3 - Alpha Development Status',
            'Environment :: Console',
            'License :: OSI Approved :: GNU General Public License (GPL)',
            'Programming Language :: Python :: 2.7',
            'Topic :: System :: Archiving',
        ])
