import flask
import rethinkstuff

app = flask.Flask(__name__)

r = rethinkstuff.Rethinker(["wbgrp-svc020", "wbgrp-svc035", "wbgrp-svc036"],
                           db="archiveit_brozzler")

@app.route("/")
def jobs():
    return flask.render_template("jobs.html", jobs=r.table("jobs").run())
    # return "\n".join(("{} ({})".format(j["id"], j["status"]) for j in jobs))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=True)

