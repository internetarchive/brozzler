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

@app.route("/api/jobs/<int:job_id>/sites")
def sites(job_id):
    sites_ = r.table("sites").get_all(job_id, index="job_id").run()
    return flask.jsonify(sites=sites_)

@app.route("/api/jobs/<int:job_id>")
def job(job_id):
    job_ = r.table("jobs").get(job_id).run()
    return flask.jsonify(job_)

@app.route("/api/jobs")
def jobs():
    jobs_ = list(r.table("jobs").run())
    return flask.jsonify(jobs=jobs_)

@app.route("/", defaults={"path": ""})
@app.route('/<path:path>')
def root(path):
    return app.send_static_file("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=True)

