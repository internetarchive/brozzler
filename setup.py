# vim: set sw=4 et:

import setuptools
import glob

VERSION_BYTES = b'0.2'

def full_version_bytes():
    import subprocess, time
    try:
        git_status = subprocess.check_output(['git', 'status'])
        line1 = git_status[:git_status.find(b'\n')]
        git_head = line1.split()[-1]

        t_bytes = subprocess.check_output(['git', 'log', '-1', '--pretty=format:%ct'])
        t = int(t_bytes.strip().decode('utf-8'))
        tm = time.gmtime(t)
        timestamp_utc = time.strftime("%Y%m%d%H%M%S", time.gmtime(t))
        return VERSION_BYTES + b'-' + git_head.strip() + b'-' + timestamp_utc.encode('utf-8')
    except subprocess.CalledProcessError:
        return VERSION_BYTES

version_bytes = full_version_bytes()
with open('umbra/version.txt', 'wb') as out:
    out.write(version_bytes)
    out.write(b'\n');

setuptools.setup(name='umbra',
        version=version_bytes.decode('utf-8'),
        description='Browser automation via chrome debug protocol',
        url='https://github.com/internetarchive/umbra',
        author='Eldon Stegall',
        author_email='eldon@archive.org',
        long_description=open('README.md').read(),
        license='Apache License 2.0',
        packages=['umbra'],
        package_data={'umbra':['behaviors.d/*.js', 'version.txt']},
        install_requires=['kombu', 'websocket-client-py3==0.13.1','argparse'],
        scripts=glob.glob('bin/*'),
        zip_safe=False,
        classifiers=[
            'Development Status :: 3 - Alpha Development Status',
            'Environment :: Console',
            'License :: OSI Approved :: Apache Software License',
            'Programming Language :: Python :: 3.3',
            'Topic :: System :: Archiving',
        ])
