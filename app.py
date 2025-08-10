from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route("/ping")
def ping():
    return "pong", 200

@app.route("/envtest")
def envtest():
    return jsonify({
        "CLIENT_ID": os.getenv("CLIENT_ID"),
        "CLIENT_SECRET": "***HIDDEN***" if os.getenv("CLIENT_SECRET") else None,
        "BACKEND_URL": os.getenv("BACKEND_URL"),
        "DATABASE_URL": "***HIDDEN***" if os.getenv("DATABASE_URL") else None
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
