from flask import Flask, request, redirect, jsonify, send_from_directory
from dotenv import load_dotenv
import json
import os
from datetime import datetime
import requests
import psycopg2

# === ŁADUJEMY ZMIENNE ŚRODOWISKOWE ===
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
DATA_FILE = "verific_data.json"

# WALIDACJA ZMIENNYCH
missing = []
for var in ["CLIENT_ID", "CLIENT_SECRET", "BACKEND_URL", "DATABASE_URL"]:
    if not os.getenv(var):
        missing.append(var)

if missing:
    raise RuntimeError(f"❌ Brakuje zmiennych środowiskowych: {', '.join(missing)}")

# === Łączenie z bazą PostgreSQL ===
try:
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()
    print("✅ Połączono z bazą PostgreSQL")
except Exception as e:
    raise RuntimeError(f"❌ Błąd połączenia z bazą: {e}")

# === Inicjalizacja pliku danych dla weryfikacji ===
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# === Flask konfiguracja ===
app = Flask(__name__)
REDIRECT_URI = f"{BACKEND_URL}/callback"

# === Statyczne pliki (np. obraz tła) ===
@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

# 🌐 TEST: sprawdzenie zmiennych środowiskowych
@app.route("/envtest")
def envtest():
    return jsonify({
        "CLIENT_ID": CLIENT_ID,
        "CLIENT_SECRET": "***UKRYTY***",
        "BACKEND_URL": BACKEND_URL,
        "DATABASE_URL": "***UKRYTY***"
    })

# 🌐 TEST: sprawdzenie połączenia z bazą
@app.route("/db_health")
def db_health():
    try:
        cur.execute("SELECT NOW();")
        ts = cur.fetchone()[0]
        return jsonify({"status": "ok", "timestamp": str(ts)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# === Główna strona backendu ===
@app.route("/")
def home():
    return "✅ Backend działa! Pizdzik pozdrawia 🐷"

# === Start weryfikacji ===
@app.route("/verify")
def verify():
    token = request.args.get("token")
    if not token:
        return "❌ Brak tokenu", 400

    db = load_data()
    db[token] = {
        "verified": False,
        "ip": request.remote_addr,
        "init": str(datetime.utcnow())
    }
    save_data(db)

    oauth_url = (
        f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify&state={token}"
    )
    return redirect(oauth_url)

# === Callback po logowaniu Discord OAuth2 ===
@app.route("/callback")
def callback():
    code = request.args.get("code")
    state_token = request.args.get("state")

    # Wymiana kodu na access_token
    try:
        r = requests.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5
        )
        tokens = r.json()
    except requests.exceptions.RequestException as e:
        return f"❌ Błąd połączenia z Discord API: {e}", 500

    access_token = tokens.get("access_token")
    if not access_token:
        return f"❌ Błąd autoryzacji: {tokens}", 400

    # Pobranie danych użytkownika
    user_data = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=5
    ).json()

    # Wiek konta
    user_id = int(user_data["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    # Zapis do verific_data.json
    db = load_data()
    if state_token in db:
        db[state_token]["discord_id"] = str(user_id)
        db[state_token]["username"] = f"{user_data['username']}#{user_data['discriminator']}"
        db[state_token]["days_old"] = days_old
        db[state_token]["verified"] = days_old >= 3
        save_data(db)

    # HTML z tłem i guzikiem WYJDŹ
    verified_text = "✅ Weryfikacja zakończona!" if days_old >= 3 else "⛔ Konto za młode!"
    color = "#4CAF50" if days_old >= 3 else "#d9534f"

    html = f"""
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Pizdzik Weryfikacja</title>
        <style>
            body {{
                margin: 0;
                height: 100vh;
                background: url('/nocne-rozkminy.jpg') no-repeat center center fixed;
                background-size: cover;
                display: flex;
                justify-content: center;
                align-items: center;
                flex-direction: column;
                color: white;
                font-family: Arial, sans-serif;
                text-shadow: 2px 2px 5px rgba(0,0,0,0.8);
            }}
            .button {{
                background-color: {color};
                padding: 20px 40px;
                font-size: 24px;
                border: none;
                border-radius: 10px;
                color: white;
                cursor: pointer;
                text-decoration: none;
                margin-top: 20px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.5);
                transition: transform 0.2s;
            }}
            .button:hover {{ transform: scale(1.1); }}
        </style>
    </head>
    <body>
        <h1>{verified_text}</h1>
        <p>Twoje konto ma {days_old} dni.</p>
        <a href="https://discord.com/channels/@me" class="button">🚪 Wyjdź</a>
    </body>
    </html>
    """
    return html

# === Status weryfikacji dla bota ===
@app.route("/status/<user_id>")
def status(user_id):
    db = load_data()
    return jsonify({"verified": db.get(user_id, {}).get("verified", False)})

# === Podgląd logów ===
@app.route("/admin/logs")
def logs():
    return load_data()

# === Start aplikacji ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
