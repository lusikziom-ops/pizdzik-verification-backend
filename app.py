from flask import Flask, request, redirect, jsonify, send_from_directory
from dotenv import load_dotenv
import os
import json
from datetime import datetime
import requests
import psycopg2

# === ŁADOWANIE ZMIENNYCH ENV ===
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")
DATABASE_URL = (
    os.getenv("DATABASE_PRIVATE_URL")
    or os.getenv("RAILWAY_PRIVATE_URL")
    or os.getenv("DATABASE_URL")
    or os.getenv("DATABASE_PUBLIC_URL")
)
DATA_FILE = "verific_data.json"
REDIRECT_URI = f"{BACKEND_URL}/callback"

if not CLIENT_ID or not CLIENT_SECRET or not BACKEND_URL:
    raise RuntimeError("❌ Brak wymaganych zmiennych środowiskowych!")

# Backup JSON – fallback jeśli brak DB
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

app = Flask(__name__)

# Statyczny serwer plików (np. tło)
@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

@app.route("/")
def home():
    return "✅ Backend weryfikacji działa!"

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
        f"https://discord.com/api/oauth2/authorize?"
        f"client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify&state={token}"
    )
    return redirect(oauth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state_token = request.args.get("state")
    if not code:
        return "❌ Brak kodu", 400

    # Wymiana kodu na token
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers, timeout=5)
    tokens = r.json()

    access_token = tokens.get("access_token")
    if not access_token:
        return "❌ Błąd OAuth", 400

    # Pobranie danych użytkownika
    headers = {"Authorization": f"Bearer {access_token}"}
    user = requests.get("https://discord.com/api/users/@me", headers=headers, timeout=5).json()

    user_id = int(user["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    # Zapis do pliku JSON jako fallback
    db = load_data()
    db[state_token] = {
        "discord_id": str(user_id),
        "username": f"{user['username']}#{user['discriminator']}",
        "days_old": days_old,
        "verified": days_old >= 3
    }
    save_data(db)

    # Przygotowanie HTML-a
    if days_old >= 3:
        status_text = "✅ Weryfikacja zakończona!"
        status_color = "#4CAF50"
        button_text = "Wejdź na serwer"
        button_link = "https://discord.gg/twoj_link"  # <--- Twój link do Discorda
    else:
        status_text = "⛔ Twoje konto jest za młode!"
        status_color = "#d9534f"
        button_text = "Wyjdź"
        button_link = "https://discord.com/channels/@me"

    html = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Weryfikacja</title>
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
                backdrop-filter: brightness(0.7);
            }}
            h1 {{
                font-size: 3em;
                color: {status_color};
                margin-bottom: 20px;
                animation: fadeIn 1s ease-in-out;
            }}
            h2 {{
                font-size: 1.5em;
                margin-bottom: 30px;
                animation: fadeIn 1.5s ease-in-out;
            }}
            .button {{
                background-color: {status_color};
                padding: 20px 40px;
                font-size: 24px;
                border-radius: 10px;
                color: white;
                text-decoration: none;
                box-shadow: 0 5px 15px rgba(0,0,0,0.5);
                transition: transform 0.2s;
            }}
            .button:hover {{
                transform: scale(1.1);
            }}
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(-20px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
        </style>
    </head>
    <body>
        <h1>{status_text}</h1>
        <h2>Twoje konto ma {days_old} dni.</h2>
        <a href="{button_link}" class="button">{button_text}</a>
    </body>
    </html>
    """
    return html

@app.route("/status/<user_id>")
def status(user_id):
    db = load_data()
    return jsonify({"verified": db.get(user_id, {}).get("verified", False)})

# Start dla Railway
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
