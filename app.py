from flask import Flask, request, redirect, jsonify, send_from_directory
from dotenv import load_dotenv
import json
import os
from datetime import datetime
import requests

# === ŁADOWANIE ZMIENNYCH Z .env ===
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")

# === WALIDACJA ZMIENNYCH ===
missing = []
if not CLIENT_ID:
    missing.append("CLIENT_ID")
if not CLIENT_SECRET:
    missing.append("CLIENT_SECRET")
if not BACKEND_URL:
    missing.append("BACKEND_URL")

if missing:
    raise RuntimeError(f"❌ Brak wymaganych zmiennych środowiskowych: {', '.join(missing)}. "
                       f"Uzupełnij je w .env lub w panelu hostingu i zrestartuj backend.")

# === KONFIGURACJA FLASK ===
app = Flask(__name__)
DATA_FILE = "verific_data.json"
REDIRECT_URI = f"{BACKEND_URL}/callback"

# === INICJALIZACJA BAZY DANYCH ===
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# === STATYCZNE TŁO ===
@app.route('/<path:filename>')
def serve_static(filename):
    """Serwuje pliki statyczne (np. nocne-rozkminy.jpg)"""
    return send_from_directory('.', filename)

# === DEBUG: SPRAWDZENIE ZMIENNYCH ŚRODOWISKOWYCH ===
@app.route("/envtest")
def envtest():
    return jsonify({
        "CLIENT_ID": CLIENT_ID,
        "CLIENT_SECRET": "***HIDDEN***" if CLIENT_SECRET else None,
        "BACKEND_URL": BACKEND_URL
    })

# === STRONA GŁÓWNA BACKENDU ===
@app.route("/")
def home():
    return "✅ Backend weryfikacji działa! Pizdzik pozdrawia 🐷"

# === ETAP 1: GENEROWANIE LINKU OAUTH2 ===
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

# === ETAP 2: CALLBACK PO LOGOWANIU DISCORDA ===
@app.route("/callback")
def callback():
    code = request.args.get("code")
    state_token = request.args.get("state")

    # Wymiana kodu OAuth2 na access_token
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    tokens = r.json()

    access_token = tokens.get("access_token")
    if not access_token:
        return "❌ Błąd autoryzacji (access_token brak)", 400

    # Pobranie info o użytkowniku
    headers = {"Authorization": f"Bearer {access_token}"}
    user_data = requests.get("https://discord.com/api/users/@me", headers=headers).json()

    # Obliczenie wieku konta
    user_id = int(user_data["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    # Zapis danych
    db = load_data()
    if state_token in db:
        db[state_token]["discord_id"] = str(user_id)
        db[state_token]["username"] = f"{user_data['username']}#{user_data['discriminator']}"
        db[state_token]["days_old"] = days_old
        db[state_token]["verified"] = days_old >= 3  # minimalny wiek konta
        save_data(db)

    # HTML z tłem i guzikiem WYJDŹ
    verified_text = "✅ Weryfikacja zakończona!" if days_old >= 3 else "⛔ Konto za młode!"
    color = "#4CAF50" if days_old >= 3 else "#d9534f"

    html = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Weryfikacja Pizdzik</title>
        <style>
            body {{
                margin: 0;
                height: 100vh;
                background: url('/nocne-rozkminy.jpg') no-repeat center center fixed;
                background-size: cover;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                font-family: Arial, sans-serif;
                color: white;
                text-shadow: 2px 2px 5px rgba(0,0,0,0.8);
            }}
            h1 {{
                font-size: 2.5em;
                margin-bottom: 20px;
            }}
            .button {{
                background-color: {color};
                border: none;
                color: white;
                padding: 20px 40px;
                text-align: center;
                text-decoration: none;
                font-size: 24px;
                border-radius: 10px;
                cursor: pointer;
                box-shadow: 0px 5px 15px rgba(0,0,0,0.5);
                transition: transform 0.2s;
            }}
            .button:hover {{
                transform: scale(1.1);
            }}
        </style>
    </head>
    <body>
        <h1>{verified_text} Twoje konto ma {days_old} dni.</h1>
        <a href="https://discord.com/channels/@me" class="button">🚪 Wyjdź</a>
    </body>
    </html>
    """
    return html

# === STATUS WERYFIKACJI DLA BOTA ===
@app.route("/status/<user_id>")
def status(user_id):
    db = load_data()
    return jsonify({"verified": db.get(user_id, {}).get("verified", False)})

# === PODGLĄD LOGÓW ADMINA ===
@app.route("/admin/logs")
def logs():
    return load_data()

# === START BACKENDU ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
