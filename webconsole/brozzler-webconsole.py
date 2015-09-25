import flask
import rethinkstuff
import json
import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
        format="%(asctime)s %(process)d %(levelname)s %(threadName)s %(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s")

app = flask.Flask(__name__, static_url_path="")

r = rethinkstuff.Rethinker(["wbgrp-svc020", "wbgrp-svc035", "wbgrp-svc036"],
                           db="archiveit_brozzler")

@app.route("/api/jobs")
def jobs():
    return flask.jsonify(jobs=list(r.table("jobs").run()))

@app.route("/")
def root():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=True)

