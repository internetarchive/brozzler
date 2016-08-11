'''
brozzler/webconsole/__init__.py - flask app for brozzler web console, defines
api endspoints etc

Copyright (C) 2014-2016 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

import logging
import sys
try:
    import flask
except ImportError as e:
    logging.critical(
            '%s: %s\n\nYou might need to run "pip install '
            'brozzler[webconsole]".\nSee README.rst for more information.',
            type(e).__name__, e)
    sys.exit(1)
import rethinkstuff
import json
import os
import importlib
import rethinkdb
import yaml
import base64

# flask does its own logging config
# logging.basicConfig(
#         stream=sys.stdout, level=logging.INFO,
#         format=(
#             "%(asctime)s %(process)d %(levelname)s %(threadName)s "
#             "%(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s")

app = flask.Flask(__name__)

# http://stackoverflow.com/questions/26578733/why-is-flask-application-not-creating-any-logs-when-hosted-by-gunicorn
gunicorn_error_logger = logging.getLogger('gunicorn.error')
app.logger.handlers.extend(gunicorn_error_logger.handlers)
app.logger.setLevel(logging.INFO)

# configure with environment variables
SETTINGS = {
    'RETHINKDB_SERVERS': os.environ.get(
        'RETHINKDB_SERVERS', 'localhost').split(','),
    'RETHINKDB_DB': os.environ.get('RETHINKDB_DB', 'brozzler'),
    'WAYBACK_BASEURL': os.environ.get(
        'WAYBACK_BASEURL', 'http://localhost:8091/brozzler'),
}
r = rethinkstuff.Rethinker(
        SETTINGS['RETHINKDB_SERVERS'], db=SETTINGS['RETHINKDB_DB'])
_svc_reg = None
def service_registry():
    global _svc_reg
    if not _svc_reg:
        _svc_reg = rethinkstuff.ServiceRegistry(r)
    return _svc_reg

@app.route("/api/sites/<site_id>/queued_count")
@app.route("/api/site/<site_id>/queued_count")
def queued_count(site_id):
    count = r.table("pages").between(
            [site_id, 0, False, r.minval], [site_id, 0, False, r.maxval],
            index="priority_by_site").count().run()
    return flask.jsonify(count=count)

@app.route("/api/sites/<site_id>/queue")
@app.route("/api/site/<site_id>/queue")
def queue(site_id):
    app.logger.info("flask.request.args=%s", flask.request.args)
    start = flask.request.args.get("start", 0)
    end = flask.request.args.get("end", start + 90)
    queue_ = r.table("pages").between(
            [site_id, 0, False, r.minval], [site_id, 0, False, r.maxval],
            index="priority_by_site")[start:end].run()
    return flask.jsonify(queue_=list(queue_))

@app.route("/api/sites/<site_id>/pages_count")
@app.route("/api/site/<site_id>/pages_count")
@app.route("/api/sites/<site_id>/page_count")
@app.route("/api/site/<site_id>/page_count")
def page_count(site_id):
    count = r.table("pages").between(
            [site_id, 1, False, r.minval],
            [site_id, r.maxval, False, r.maxval],
            index="priority_by_site").count().run()
    return flask.jsonify(count=count)

@app.route("/api/sites/<site_id>/pages")
@app.route("/api/site/<site_id>/pages")
def pages(site_id):
    """Pages already crawled."""
    app.logger.info("flask.request.args=%s", flask.request.args)
    start = int(flask.request.args.get("start", 0))
    end = int(flask.request.args.get("end", start + 90))
    pages_ = r.table("pages").between(
            [site_id, 1, r.minval], [site_id, r.maxval, r.maxval],
            index="least_hops").order_by(index="least_hops")[start:end].run()
    return flask.jsonify(pages=list(pages_))

@app.route("/api/pages/<page_id>")
@app.route("/api/page/<page_id>")
def page(page_id):
    page_ = r.table("pages").get(page_id).run()
    return flask.jsonify(page_)

@app.route("/api/pages/<page_id>/yaml")
@app.route("/api/page/<page_id>/yaml")
def page_yaml(page_id):
    page_ = r.table("pages").get(page_id).run()
    return app.response_class(
            yaml.dump(page_, default_flow_style=False),
            mimetype='application/yaml')

@app.route("/api/sites/<site_id>")
@app.route("/api/site/<site_id>")
def site(site_id):
    s = r.table("sites").get(site_id).run()
    if "cookie_db" in s:
        s["cookie_db"] = base64.b64encode(s["cookie_db"]).decode("ascii")
    return flask.jsonify(s)

@app.route("/api/sites/<site_id>/yaml")
@app.route("/api/site/<site_id>/yaml")
def site_yaml(site_id):
    site_ = r.table("sites").get(site_id).run()
    return app.response_class(
            yaml.dump(site_, default_flow_style=False),
            mimetype='application/yaml')

@app.route("/api/stats/<bucket>")
def stats(bucket):
    stats_ = r.table("stats").get(bucket).run()
    return flask.jsonify(stats_)

@app.route("/api/jobs/<int:job_id>/sites")
@app.route("/api/job/<int:job_id>/sites")
def sites(job_id):
    sites_ = list(r.table("sites").get_all(job_id, index="job_id").run())
    # TypeError: <binary, 7168 bytes, '53 51 4c 69 74 65...'> is not JSON serializable
    for s in sites_:
        if "cookie_db" in s:
            s["cookie_db"] = base64.b64encode(s["cookie_db"]).decode("ascii")
    return flask.jsonify(sites=sites_)

@app.route("/api/jobless-sites")
def jobless_sites():
    # XXX inefficient (unindexed) query
    sites_ = list(r.table("sites").filter(~r.row.has_fields("job_id")).run())
    # TypeError: <binary, 7168 bytes, '53 51 4c 69 74 65...'> is not JSON serializable
    for s in sites_:
        if "cookie_db" in s:
            s["cookie_db"] = base64.b64encode(s["cookie_db"]).decode("ascii")
    return flask.jsonify(sites=sites_)

@app.route("/api/jobs/<int:job_id>")
@app.route("/api/job/<int:job_id>")
def job(job_id):
    job_ = r.table("jobs").get(job_id).run()
    return flask.jsonify(job_)

@app.route("/api/jobs/<int:job_id>/yaml")
@app.route("/api/job/<int:job_id>/yaml")
def job_yaml(job_id):
    job_ = r.table("jobs").get(job_id).run()
    return app.response_class(
            yaml.dump(job_, default_flow_style=False),
            mimetype='application/yaml')

@app.route("/api/workers")
def workers():
    workers_ = service_registry().available_services("brozzler-worker")
    return flask.jsonify(workers=list(workers_))

@app.route("/api/services")
def services():
    services_ = service_registry().available_services()
    return flask.jsonify(services=list(services_))

@app.route("/api/jobs")
def jobs():
    jobs_ = list(r.table("jobs").order_by(rethinkdb.desc("id")).run())
    return flask.jsonify(jobs=jobs_)

@app.route("/api/config")
def config():
    return flask.jsonify(config=SETTINGS)

@app.route("/api/<path:path>")
@app.route("/api", defaults={"path":""})
def api404(path):
    flask.abort(404)

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def root(path):
    return flask.render_template("index.html")

try:
    import gunicorn.app.base
    from gunicorn.six import iteritems

    class GunicornBrozzlerWebConsole(gunicorn.app.base.BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super(GunicornBrozzlerWebConsole, self).__init__()

        def load_config(self):
            config = dict(
                    [(key, value) for key, value in iteritems(self.options)
                        if key in self.cfg.settings and value is not None])
            for key, value in iteritems(config):
                self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    def run(**options):
        logging.info('running brozzler-webconsole using gunicorn')
        GunicornBrozzlerWebConsole(app, options).run()

except ImportError:
    def run():
        logging.info('running brozzler-webconsole using simple flask app.run')
        app.run()

def main():
    import argparse
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(sys.argv[0]),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=(
                'brozzler-webconsole - web application for viewing brozzler '
                'crawl status'),
            epilog=(
                'brozzler-webconsole has no command line options, but can be '
                'configured using the following environment variables:\n\n'
                '  RETHINKDB_SERVERS   rethinkdb servers, e.g. db0.foo.org,'
                'db0.foo.org:38015,db1.foo.org (default: localhost)\n'
                '  RETHINKDB_DB        rethinkdb database name (default: '
                'brozzler)\n'
                '  WAYBACK_BASEURL     base url for constructing wayback '
                'links (default http://localhost:8091/brozzler)'))
    args = arg_parser.parse_args(args=sys.argv[1:])
    run()

if __name__ == "__main__":
    main()

