import flask
import rethinkstuff
import json
import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
        format="%(asctime)s %(process)d %(levelname)s %(threadName)s %(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s")

app = flask.Flask(__name__)

r = rethinkstuff.Rethinker(["wbgrp-svc020", "wbgrp-svc035", "wbgrp-svc036"],
                           db="archiveit_brozzler")

@app.route("/api/sites/<site_id>/queued_count")
@app.route("/api/site/<site_id>/queued_count")
def queued_count(site_id):
    count = r.table("pages").between([site_id, 0, False, r.minval], [site_id, 0, False, r.maxval], index="priority_by_site").count().run()
    return flask.jsonify(count=count)

@app.route("/api/sites/<site_id>/queue")
@app.route("/api/site/<site_id>/queue")
def queue(site_id):
    logging.info("flask.request.args=%s", flask.request.args)
    start = flask.request.args.get("start", 0)
    end = flask.request.args.get("end", start + 90)
    queue_ = r.table("pages").between([site_id, 0, False, r.minval], [site_id, 0, False, r.maxval], index="priority_by_site")[start:end].run()
    return flask.jsonify(queue_=list(queue_))

@app.route("/api/sites/<site_id>/pages_count")
@app.route("/api/site/<site_id>/pages_count")
@app.route("/api/sites/<site_id>/page_count")
@app.route("/api/site/<site_id>/page_count")
def page_count(site_id):
    count = r.table("pages").between([site_id, 1, False, r.minval], [site_id, r.maxval, False, r.maxval], index="priority_by_site").count().run()
    return flask.jsonify(count=count)

@app.route("/api/sites/<site_id>/pages")
@app.route("/api/site/<site_id>/pages")
def pages(site_id):
    """Pages already crawled."""
    logging.info("flask.request.args=%s", flask.request.args)
    start = int(flask.request.args.get("start", 0))
    end = int(flask.request.args.get("end", start + 90))
    pages_ = r.table("pages").between([site_id, 1, False, r.minval], [site_id, r.maxval, False, r.maxval], index="priority_by_site")[start:end].run()
    return flask.jsonify(pages=list(pages_))

@app.route("/api/sites/<site_id>")
@app.route("/api/site/<site_id>")
def site(site_id):
    site_ = r.table("sites").get(site_id).run()
    return flask.jsonify(site_)

@app.route("/api/stats/<bucket>")
def stats(bucket):
    stats_ = r.table("stats").get(bucket).run()
    return flask.jsonify(stats_)

@app.route("/api/jobs/<int:job_id>/sites")
@app.route("/api/job/<int:job_id>/sites")
def sites(job_id):
    sites_ = r.table("sites").get_all(job_id, index="job_id").run()
    return flask.jsonify(sites=list(sites_))

@app.route("/api/jobs/<int:job_id>")
@app.route("/api/job/<int:job_id>")
def job(job_id):
    job_ = r.table("jobs").get(job_id).run()
    return flask.jsonify(job_)

@app.route("/api/jobs")
def jobs():
    jobs_ = list(r.table("jobs").run())
    return flask.jsonify(jobs=jobs_)

@app.route("/api/<path:path>")
@app.route("/api", defaults={"path":""})
def api404(path):
    flask.abort(404)

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def root(path):
    return app.send_static_file("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=True)

