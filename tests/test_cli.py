#!/usr/bin/env python
"""
test_cli.py - test brozzler commands

Copyright (C) 2017 Internet Archive

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

import brozzler.cli
import pkg_resources
import pytest
import subprocess
import doublethink


def cli_commands():
    commands = set(pkg_resources.get_entry_map("brozzler")["console_scripts"].keys())
    commands.remove("brozzler-wayback")
    try:
        import gunicorn
    except ImportError:
        commands.remove("brozzler-dashboard")
    try:
        import pywb
    except ImportError:
        commands.remove("brozzler-easy")
    return commands


@pytest.mark.parametrize("cmd", cli_commands())
def test_call_entrypoint(capsys, cmd):
    entrypoint = pkg_resources.get_entry_map("brozzler")["console_scripts"][cmd]
    callable = entrypoint.resolve()
    with pytest.raises(SystemExit):
        callable(["/whatever/bin/%s" % cmd, "--version"])
    out, err = capsys.readouterr()
    assert out == "brozzler %s - %s\n" % (brozzler.__version__, cmd)
    assert err == ""


@pytest.mark.parametrize("cmd", cli_commands())
def test_run_command(capsys, cmd):
    proc = subprocess.Popen(
        [cmd, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    assert err == b""
    assert out == ("brozzler %s - %s\n" % (brozzler.__version__, cmd)).encode("ascii")


def test_rethinkdb_up():
    """Check that rethinkdb is up and running."""
    # check that rethinkdb is listening and looks sane
    rr = doublethink.Rethinker(db="rethinkdb")  # built-in db
    tbls = rr.table_list().run()
    assert len(tbls) > 10


# XXX don't know why this test is failing in travis-ci and vagrant while
# test_call_entrypoint tests pass :( (also fails with capfd)
@pytest.mark.xfail
def test_stop_nonexistent_crawl(capsys):
    with pytest.raises(SystemExit):
        brozzler.cli.brozzler_stop_crawl(["brozzler-stop-crawl", "--site=123"])
    out, err = capsys.readouterr()
    assert err.endswith("site not found with id=123\n")
    assert out == ""

    with pytest.raises(SystemExit):
        brozzler.cli.brozzler_stop_crawl(["brozzler-stop-crawl", "--job=abc"])
    out, err = capsys.readouterr()
    assert err.endswith("""job not found with id='abc'\n""")
    assert out == ""
