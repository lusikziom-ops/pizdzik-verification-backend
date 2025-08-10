from flask import Flask, jsonify
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

@app.route("/ping")
def ping():
    return "pong", 200

@app.route("/envtest")
def envtest():
    return jsonify({
        "CLIENT_ID": os.getenv("CLIENT_ID") or None,
        "CLIENT_SECRET": "***HIDDEN***" if os.getenv("CLIENT_SECRET") else None,
        "BACKEND_URL": os.getenv("BACKEND_URL") or None,
        "DATABASE_URL": "***HIDDEN***" if os.getenv("DATABASE_URL") else None
    })

@app.route("/db_health")
def db_health():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return jsonify({"status": "error", "error": "Brak DATABASE_URL"}), 500
    try:
        conn = psycopg2.connect(db_url, sslmode="require", connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT NOW();")
        ts = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "timestamp": str(ts)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Startuję Flask na porcie {port}")
    app.run(host="0.0.0.0", port=port)
