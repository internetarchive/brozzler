import setuptools
import glob

setuptools.setup(name='brozzler',
        version='1.1.dev4',
        description='Distributed web crawling with browsers',
        url='https://github.com/nlevitt/brozzler',
        author='Noah Levitt',
        author_email='nlevitt@archive.org',
        long_description=open('README.rst').read(),
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
