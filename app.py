from flask import Flask, request, redirect, jsonify
import json
import os
from datetime import datetime
import requests

app = Flask(__name__)
DATA_FILE = "verific_data.json"

# Utwórz pusty plik bazy, jeśli go nie ma
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

CLIENT_ID = os.getenv("CLIENT_ID")  # ID aplikacji Discord
CLIENT_SECRET = os.getenv("CLIENT_SECRET")  # Secret aplikacji Discord
BACKEND_URL = os.getenv("BACKEND_URL")  # Adres tego backendu, np. https://nazwa.railway.app
REDIRECT_URI = f"{BACKEND_URL}/callback"

@app.route("/")
def home():
    return "✅ Backend weryfikacji działa! Pizdzik pozdrawia 🐷"

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

    # Przekierowanie na logowanie Discord OAuth2
    oauth_url = (
        f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify&state={token}"
    )
    return redirect(oauth_url)

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
        return "❌ Błąd autoryzacji", 400

    # Pobranie info o użytkowniku
    headers = {"Authorization": f"Bearer {access_token}"}
    user_data = requests.get("https://discord.com/api/users/@me", headers=headers).json()

    user_id = int(user_data["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    db = load_data()
    if state_token in db:
        db[state_token]["discord_id"] = str(user_data["id"])
        db[state_token]["username"] = f"{user_data['username']}#{user_data['discriminator']}"
        db[state_token]["days_old"] = days_old
        db[state_token]["verified"] = days_old >= 3  # minimalny wiek konta, np. 3 dni
        save_data(db)

    return f"✅ Weryfikacja zakończona! Twoje konto ma {days_old} dni."

@app.route("/status/<user_id>")
def status(user_id):
    db = load_data()
    return jsonify({"verified": db.get(user_id, {}).get("verified", False)})

@app.route("/admin/logs")
def logs():
    """Podgląd logów weryfikacji"""
    return load_data()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
