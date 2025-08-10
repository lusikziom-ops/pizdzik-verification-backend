from flask import Flask, jsonify
from dotenv import load_dotenv
import psycopg2
import os

# === ŁADUJEMY ZMIENNE Z ENV ===
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

# === ENDPOINT TESTOWY ENV ===
@app.route("/envtest")
def envtest():
    return jsonify({
        "CLIENT_ID": CLIENT_ID or None,
        "CLIENT_SECRET": "***HIDDEN***" if CLIENT_SECRET else None,
        "BACKEND_URL": BACKEND_URL or None,
        "DATABASE_URL": "***HIDDEN***" if DATABASE_URL else None,
        "PORT": PORT
    })

# === ENDPOINT DB HEALTH ===
@app.route("/db_health")
def db_health():
    if not DATABASE_URL:
        return jsonify({"status": "error", "error": "Brak DATABASE_URL"}), 500

    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            sslmode="require",
            connect_timeout=5  # nie wisimy w nieskończoność
        )
        cur = conn.cursor()
        cur.execute("SELECT NOW();")
        result = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "timestamp": str(result)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# === ENDPOINT SZYBKIEJ ODPOWIEDZI ===
@app.route("/ping")
def ping():
    return "pong"

# === MAIN ===
if __name__ == "__main__":
    print("=== DEBUG ENV VARIABLES ===")
    print("CLIENT_ID:", CLIENT_ID)
    print("CLIENT_SECRET:", "***HIDDEN***" if CLIENT_SECRET else None)
    print("BACKEND_URL:", BACKEND_URL)
    print("DATABASE_URL:", "***HIDDEN***" if DATABASE_URL else None)
    print("PORT:", PORT)
    print("===========================")

    app.run(host="0.0.0.0", port=PORT)
