# vim: set sw=4 et:

import setuptools
import glob

VERSION_BYTES = b'1.0'

def full_version_bytes():
    import subprocess, time
    try:
        commit_bytes = subprocess.check_output(['git', 'log', '-1', '--pretty=format:%h'])
        t_bytes = subprocess.check_output(['git', 'log', '-1', '--pretty=format:%ct'])
        t = int(t_bytes.strip().decode('utf-8'))
        tm = time.gmtime(t)
        timestamp_utc = time.strftime("%Y%m%d%H%M%S", time.gmtime(t))
        return VERSION_BYTES + b'-' + timestamp_utc.encode('utf-8') + b'-' + commit_bytes.strip()
    except subprocess.CalledProcessError:
        return VERSION_BYTES

version_bytes = full_version_bytes()
with open('brozzler/version.txt', 'wb') as out:
    out.write(version_bytes)
    out.write(b'\n');

setuptools.setup(name='brozzler',
        version=version_bytes.decode('utf-8'),
        description='Distributed web crawling with browsers',
        url='https://github.com/nlevitt/brozzler',
        author='Noah Levitt',
        author_email='nlevitt@archive.org',
        long_description=open('README.md').read(),
        license='Apache License 2.0',
        packages=['brozzler'],
        package_data={'brozzler':['behaviors.d/*.js*', 'behaviors.yaml', 'version.txt']},
        scripts=glob.glob('bin/*'),
        install_requires=["argparse","PyYAML","surt==HEAD","youtube-dl==HEAD","reppy==HEAD","requests","websocket-client==HEAD","rethinkdb"],
        dependency_links=[
            "git+https://github.com/nlevitt/youtube-dl.git@brozzler#egg=youtube-dl-HEAD",
            "git+https://github.com/seomoz/reppy.git#egg=reppy-HEAD",
            "git+https://github.com/nlevitt/websocket-client.git@tweaks#egg=websocket-client-HEAD",
            "git+https://github.com/nlevitt/surt.git@py3#egg=surt-HEAD",
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
