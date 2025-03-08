"""
brozzler/__init__.py - __init__.py for brozzler package, contains some common
code

Copyright (C) 2014-2017 Internet Archive

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

import datetime
import logging
import threading
from importlib.metadata import version as _version

import structlog
import urlcanon

__version__ = _version("brozzler")


class ShutdownRequested(Exception):
    pass


class NothingToClaim(Exception):
    pass


class CrawlStopped(Exception):
    pass


class PageInterstitialShown(Exception):
    pass


class VideoExtractorError(Exception):
    pass


class ProxyError(Exception):
    pass


class PageConnectionError(Exception):
    pass


class ReachedTimeLimit(Exception):
    pass


class ReachedLimit(Exception):
    def __init__(self, http_error=None, warcprox_meta=None, http_payload=None):
        import json

        if http_error:
            if "warcprox-meta" in http_error.headers:
                self.warcprox_meta = json.loads(http_error.headers["warcprox-meta"])
            else:
                self.warcprox_meta = None
            self.http_payload = http_error.read()
        elif warcprox_meta:
            self.warcprox_meta = warcprox_meta
            self.http_payload = http_payload

    def __repr__(self):
        return "ReachedLimit(warcprox_meta=%r,http_payload=%r)" % (
            self.warcprox_meta if hasattr(self, "warcprox_meta") else None,
            self.http_payload if hasattr(self, "http_payload") else None,
        )

    def __str__(self):
        return self.__repr__()


# see https://github.com/internetarchive/brozzler/issues/91
def _logging_handler_handle(self, record):
    rv = self.filter(record)
    if rv:
        try:
            self.acquire()
            self.emit(record)
        finally:
            try:
                self.release()
            except:  # noqa: E722
                pass
    return rv


logging.Handler.handle = _logging_handler_handle

_behaviors = None


def behaviors(behaviors_dir=None):
    """Return list of JS behaviors loaded from YAML file.

    :param behaviors_dir: Directory containing `behaviors.yaml` and
    `js-templates/`. Defaults to brozzler dir.
    """
    import os

    import yaml

    global _behaviors
    if _behaviors is None:
        d = behaviors_dir or os.path.dirname(__file__)
        behaviors_yaml = os.path.join(d, "behaviors.yaml")
        with open(behaviors_yaml) as fin:
            _behaviors = yaml.safe_load(fin)
    return _behaviors


def behavior_script(url, template_parameters=None, behaviors_dir=None):
    """
    Returns the javascript behavior string populated with template_parameters.
    """
    import re

    logger = structlog.get_logger(logger_name=__name__)

    for behavior in behaviors(behaviors_dir=behaviors_dir):
        if re.match(behavior["url_regex"], url):
            parameters = dict()
            if "default_parameters" in behavior:
                parameters.update(behavior["default_parameters"])
            if template_parameters:
                parameters.update(template_parameters)
            template = jinja2_environment(behaviors_dir).get_template(
                behavior["behavior_js_template"]
            )
            script = template.render(parameters)
            logger.info(
                "rendering template",
                template=behavior["behavior_js_template"],
                parameters=parameters,
                url=url,
            )
            return script
    return None


class ThreadExceptionGate:
    logger = structlog.get_logger(logger_name=__module__ + "." + __qualname__)

    def __init__(self, thread):
        self.thread = thread
        self.ok_to_raise = threading.Event()
        self.pending_exception = None
        self.lock = threading.RLock()

    def __enter__(self):
        assert self.thread == threading.current_thread()
        if self.pending_exception:
            self.logger.info(
                "raising pending exception", pending_exception=self.pending_exception
            )
            tmp = self.pending_exception
            self.pending_exception = None
            raise tmp
        else:
            self.ok_to_raise.set()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        assert self.thread == threading.current_thread()
        self.ok_to_raise.clear()
        return False  # don't swallow exception

    def queue_exception(self, e):
        with self.lock:
            if self.pending_exception:
                self.logger.warning(
                    "exception already pending for thread, discarding",
                    pending_exception=self.pending_exception,
                    thread=self.thread,
                    discarded_exception=e,
                )
            else:
                self.pending_exception = e

    def __repr__(self):
        return "<ThreadExceptionGate(%s)>" % self.thread


_thread_exception_gates = {}
_thread_exception_gates_lock = threading.Lock()


def thread_exception_gate(thread=None):
    """
    Returns a `ThreadExceptionGate` for `thread` (current thread by default).

    `ThreadExceptionGate` is a context manager which allows exceptions to be
    raised from threads other than the current one, by way of `thread_raise`.

    Example:

        try:
            with thread_exception_gate():
                # do something
        except:
            # handle exception....

    If `thread_raise` is called on a thread that is not currently inside the
    `ThreadExceptionGate` context (pep340 "runtime environment"), the exception
    is queued, and raised immediately if and when the thread enters the
    context. Only one exception will be queued this way at a time, others are
    discarded.
    """
    if not thread:
        thread = threading.current_thread()

    with _thread_exception_gates_lock:
        if thread not in _thread_exception_gates:
            _thread_exception_gates[thread] = ThreadExceptionGate(thread)

    return _thread_exception_gates[thread]


thread_accept_exceptions = thread_exception_gate


def thread_raise(thread, exctype):
    """
    Raises or queues the exception `exctype` for the thread `thread`.

    See the documentation on the function `thread_exception_gate()` for more
    information.

    Adapted from http://tomerfiliba.com/recipes/Thread2/ which explains:
    "The exception will be raised only when executing python bytecode. If your
    thread calls a native/built-in blocking function, the exception will be
    raised only when execution returns to the python code."

    Raises:
        TypeError if `exctype` is not a class
        ValueError, SystemError in case of unexpected problems
    """
    import ctypes
    import inspect

    import structlog

    logger = structlog.get_logger(exctype=exctype, thread=thread)

    if not inspect.isclass(exctype):
        raise TypeError(
            "cannot raise %s, only exception types can be raised (not "
            "instances)" % exctype
        )

    gate = thread_exception_gate(thread)
    with gate.lock:
        if gate.ok_to_raise.is_set() and thread.is_alive():
            gate.ok_to_raise.clear()
            logger.info("raising exception in thread")
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_long(thread.ident), ctypes.py_object(exctype)
            )
            if res == 0:
                raise ValueError("invalid thread id? thread.ident=%s" % thread.ident)
            elif res != 1:
                # if it returns a number greater than one, you're in trouble,
                # and you should call it again with exc=NULL to revert the effect
                ctypes.pythonapi.PyThreadState_SetAsyncExc(thread.ident, 0)
                raise SystemError("PyThreadState_SetAsyncExc failed")
        else:
            logger.info("queueing exception for thread")
            gate.queue_exception(exctype)


def sleep(duration):
    """
    Sleeps for duration seconds in increments of 0.5 seconds.

    Use this so that the sleep can be interrupted by thread_raise().
    """
    import time

    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed >= duration:
            break
        time.sleep(min(duration - elapsed, 0.5))


_jinja2_env = None


def jinja2_environment(behaviors_dir=None):
    global _jinja2_env
    if not _jinja2_env:
        import json
        import os

        import jinja2

        if behaviors_dir:
            _loader = jinja2.FileSystemLoader(
                os.path.join(behaviors_dir, "js-templates")
            )
        else:
            _loader = jinja2.PackageLoader("brozzler", "js-templates")
        _jinja2_env = jinja2.Environment(loader=_loader, auto_reload=False)
        _jinja2_env.filters["json"] = json.dumps
    return _jinja2_env


def _remove_query(url):
    url.question_mark = b""
    url.query = b""


# XXX chop off path after last slash??
site_surt_canon = urlcanon.Canonicalizer(urlcanon.semantic.steps + [_remove_query])


def _mdfind(identifier):
    import subprocess

    try:
        result = subprocess.check_output(
            ["mdfind", f"kMDItemCFBundleIdentifier == {identifier}"], text=True
        )
    # Just treat any errors as "couldn't find app"
    except subprocess.CalledProcessError:
        return None

    if result:
        return result.rstrip("\n")


def _suggest_default_chrome_exe_mac():
    import os

    path = None
    # Try Chromium first, then Chrome
    result = _mdfind("org.chromium.Chromium")
    if result is not None:
        path = f"{result}/Contents/MacOS/Chromium"

    result = _mdfind("com.google.Chrome")
    if result is not None:
        path = f"{result}/Contents/MacOS/Google Chrome"

    if path is not None and os.path.exists(path):
        return path

    # Fall back to default paths if mdfind couldn't find it
    # (mdfind might fail to find them even in their default paths
    # if the system has Spotlight disabled.)
    for path in [
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]:
        if os.path.exists(path):
            return path


def suggest_default_chrome_exe():
    import shutil
    import sys

    # First ask mdfind, which lets us find it in non-default paths
    if sys.platform == "darwin":
        path = _suggest_default_chrome_exe_mac()
        if path is not None:
            return path

    # "chromium-browser" is the executable on ubuntu trusty
    # https://github.com/internetarchive/brozzler/pull/6/files uses "chromium"
    # google chrome executable names taken from these packages:
    # http://www.ubuntuupdates.org/ppa/google_chrome
    for exe in [
        "chromium-browser",
        "chromium",
        "google-chrome",
        "google-chrome-stable",
        "google-chrome-beta",
        "google-chrome-unstable",
    ]:
        if shutil.which(exe):
            return exe
    return "chromium-browser"


EPOCH_UTC = datetime.datetime.fromtimestamp(0.0, tz=datetime.timezone.utc)

from brozzler.browser import Browser, BrowserPool, BrowsingException  # noqa: E402
from brozzler.robots import is_permitted_by_robots  # noqa: E402

__all__ = [
    "is_permitted_by_robots",
    "Browser",
    "BrowserPool",
    "BrowsingException",
    "sleep",
    "thread_accept_exceptions",
    "thread_raise",
    "suggest_default_chrome_exe",
]

# TODO try using importlib.util.find_spec to test for dependency presence
# rather than try/except on import.
# See https://docs.astral.sh/ruff/rules/unused-import/#example
try:
    import doublethink  # noqa: F401

    # All of these imports use doublethink for real and are unsafe
    # to do if doublethink is unavailable.
    from brozzler.frontier import RethinkDbFrontier  # noqa: F401
    from brozzler.model import (
        InvalidJobConf,  # noqa: F401
        Job,  # noqa: F401
        Page,  # noqa: F401
        Site,  # noqa: F401
        new_job,  # noqa: F401
        new_job_file,  # noqa: F401
        new_site,  # noqa: F401
    )
    from brozzler.worker import BrozzlerWorker  # noqa: F401

    __all__.extend(
        [
            "Page",
            "BrozzlerWorker",
            "RethinkDbFrontier",
            "Site",
            "new_job",
            "new_site",
            "Job",
            "new_job_file",
            "InvalidJobConf",
        ]
    )
except ImportError:
    pass

# we could make this configurable if there's a good reason
MAX_PAGE_FAILURES = 3
