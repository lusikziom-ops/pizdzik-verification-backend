from flask import Flask, request, redirect, jsonify
from dotenv import load_dotenv
import os
import json
from datetime import datetime
import requests

# === ŁADOWANIE ZMIENNYCH ENV ===
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")
DATA_FILE = "verific_data.json"
REDIRECT_URI = f"{BACKEND_URL}/callback"

if not CLIENT_ID or not CLIENT_SECRET or not BACKEND_URL:
    raise RuntimeError("❌ Brak wymaganych zmiennych środowiskowych!")

# === Backup JSON – jeśli nie istnieje ===
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)


def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# === Flask app ===
app = Flask(__name__, static_url_path='/static')

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

    # Wymiana kodu OAuth na access_token
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

    # Dane użytkownika z Discord API
    headers = {"Authorization": f"Bearer {access_token}"}
    user = requests.get("https://discord.com/api/users/@me", headers=headers, timeout=5).json()

    user_id = int(user["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    # Zapis do pliku
    db = load_data()
    db[state_token] = {
        "discord_id": str(user_id),
        "username": f"{user['username']}#{user['discriminator']}",
        "days_old": days_old,
        "verified": days_old >= 3
    }
    save_data(db)

    # Dynamiczny wygląd strony
    if days_old >= 3:
        status_text = "✅ Weryfikacja zakończona!"
        status_color = "#4CAF50"
        button_text = "Wejdź na serwer"
        button_link = "https://discord.gg/twoj_invite"  # Wstaw swój link zaproszenia
        sub_message = "Twoje konto wygląda na wiarygodne. Zapraszamy!"
    else:
        status_text = "⛔ Twoje konto jest za młode!"
        status_color = "#d9534f"
        button_text = "Powrót"
        button_link = "https://discord.com/channels/@me"
        sub_message = "Potrzebujemy kont o dłuższym stażu, spróbuj ponownie później."

    html = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Weryfikacja konta Discord</title>
        <style>
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            body {{
                height: 100vh;
                font-family: 'Segoe UI', Arial, sans-serif;
                background: linear-gradient(135deg, rgba(15,15,30,0.95), rgba(30,30,60,0.95)),
                            url('/static/nocne-rozkminy.jpg') center/cover no-repeat fixed;
                display: flex;
                justify-content: center;
                align-items: center;
                color: #fff;
            }}
            .card {{
                background: rgba(255, 255, 255, 0.08);
                padding: 40px;
                border-radius: 15px;
                text-align: center;
                box-shadow: 0 10px 25px rgba(0,0,0,0.5);
                max-width: 450px;
                width: 90%;
                backdrop-filter: blur(8px);
                animation: fadeIn 0.6s ease-out;
            }}
            h1 {{
                font-size: 2.4em;
                color: {status_color};
                margin-bottom: 15px;
            }}
            p {{
                margin-bottom: 25px;
                font-size: 1.1em;
                line-height: 1.4em;
                opacity: 0.9;
            }}
            .days {{
                font-size: 1.2em;
                margin-bottom: 25px;
                font-weight: 500;
                color: #ddd;
            }}
            a.button {{
                background: {status_color};
                padding: 15px 35px;
                font-size: 1.2em;
                border-radius: 8px;
                color: #fff;
                text-decoration: none;
                font-weight: bold;
                display: inline-block;
                transition: all 0.2s ease-in-out;
                box-shadow: 0 4px 15px rgba(0,0,0,0.4);
            }}
            a.button:hover {{
                transform: translateY(-3px) scale(1.05);
                box-shadow: 0 6px 20px rgba(0,0,0,0.5);
            }}
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(10px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>{status_text}</h1>
            <p>{sub_message}</p>
            <div class="days">Twoje konto ma <strong>{days_old}</strong> dni.</div>
            <a href="{button_link}" class="button">{button_text}</a>
        </div>
    </body>
    </html>
    """
    return html


@app.route("/status/<user_id>")
def status(user_id):
    db = load_data()
    return jsonify({"verified": db.get(user_id, {}).get("verified", False)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
