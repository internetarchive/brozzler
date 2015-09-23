import setuptools
import glob

VERSION_BYTES = b'1.0'

def full_version_bytes():
    import subprocess, time
    try:
        commit_num_bytes = subprocess.check_output(['git', 'rev-list', '--count', 'HEAD'])
        return VERSION_BYTES + b'.' + commit_num_bytes.strip()
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
        long_description=open('README.rst').read(),
        license='Apache License 2.0',
        packages=['brozzler'],
        package_data={'brozzler': ['behaviors.d/*.js*', 'behaviors.yaml', 'version.txt']},
        scripts=glob.glob('bin/*'),
        install_requires=[
            'PyYAML',
            'youtube-dl',
            'reppy',
            'requests',
            'websocket-client',
            'pillow',
            'surt',
            'rethinkstuff',
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
