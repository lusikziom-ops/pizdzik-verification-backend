from flask import Flask, request, redirect, jsonify, send_from_directory
from dotenv import load_dotenv
import os
import json
from datetime import datetime
import requests
from urllib.parse import quote_plus

# === ŁADOWANIE ZMIENNYCH ENV ===
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")
DATA_FILE = "verific_data.json"
REDIRECT_URI = f"{BACKEND_URL}/callback"

if not CLIENT_ID or not CLIENT_SECRET or not BACKEND_URL:
    raise RuntimeError("❌ Brak wymaganych zmiennych środowiskowych!")

# === Backup JSON – fallback jeśli brak bazy ===
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

# Serwowanie plików statycznych (np. tła nocne-rozkminy.jpg)
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

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

    # Zakodowany redirect_uri
    encoded_redirect = quote_plus(REDIRECT_URI)
    oauth_url = (
        f"https://discord.com/api/oauth2/authorize?"
        f"client_id={CLIENT_ID}"
        f"&redirect_uri={encoded_redirect}"
        f"&response_type=code&scope=identify"
        f"&state={token}"
    )
    return redirect(oauth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state_token = request.args.get("state")
    if not code:
        return "❌ Brak kodu", 400

    # --- Wymiana kodu OAuth na access_token ---
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(
        "https://discord.com/api/oauth2/token",
        data=data,
        headers=headers,
        timeout=5
    )
    tokens = r.json()

    access_token = tokens.get("access_token")
    if not access_token:
        return "❌ Błąd OAuth", 400

    # --- Pobranie danych użytkownika ---
    headers = {"Authorization": f"Bearer {access_token}"}
    user = requests.get(
        "https://discord.com/api/users/@me",
        headers=headers,
        timeout=5
    ).json()

    user_id = int(user["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    # --- Zapis do pliku/bazy ---
    db = load_data()
    verified_status = days_old >= 3
    db[state_token] = {
        "discord_id": str(user_id),
        "username": f"{user['username']}#{user['discriminator']}",
        "days_old": days_old,
        "verified": verified_status
    }
    save_data(db)

    # --- Ustal dane do wyświetlenia ---
    if verified_status:
        status_text = "✅ Weryfikacja zakończona!"
        status_color = "#4CAF50"
        button_text = "Wejdź na serwer"
        button_link = "https://discord.com/app"  # tu możesz wstawić własny link zaproszenia np. https://discord.gg/twojkod
        sub_message = "Twoje konto jest wystarczająco stare. Witamy na pokładzie!"
    else:
        status_text = "⛔ Twoje konto jest za młode!"
        status_color = "#d9534f"
        button_text = "Wróć na Discorda"
        button_link = "https://discord.com/app"
        sub_message = "Spróbuj ponownie za kilka dni, gdy konto będzie starsze."

    # --- HTML ---
    html = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Weryfikacja Discord</title>
        <style>
            body {{
                margin: 0; padding: 0;
                height: 100vh;
                font-family: 'Segoe UI', Arial, sans-serif;
                background: linear-gradient(rgba(0,0,0,0.7), rgba(0,0,0,0.7)),
                            url('/static/nocne-rozkminy.jpg') center/cover no-repeat;
                display: flex;
                justify-content: center;
                align-items: center;
                color: #fff;
            }}
            .card {{
                background: rgba(255, 255, 255, 0.1);
                padding: 40px;
                border-radius: 15px;
                text-align: center;
                box-shadow: 0 8px 20px rgba(0,0,0,0.5);
                max-width: 400px;
                width: 90%;
                backdrop-filter: blur(10px);
                animation: fadeIn 0.6s ease-out;
            }}
            h1 {{
                color: {status_color};
                margin-bottom: 15px;
                font-size: 2em;
            }}
            p {{
                font-size: 1.1em;
                margin-bottom: 20px;
                opacity: 0.95;
            }}
            .button {{
                background: {status_color};
                padding: 14px 25px;
                font-size: 1.1em;
                border-radius: 8px;
                color: #fff;
                text-decoration: none;
                font-weight: bold;
                display: inline-block;
                transition: all 0.2s ease;
            }}
            .button:hover {{
                transform: scale(1.05);
            }}
            .hint {{
                margin-top: 15px;
                font-size: 0.9em;
                opacity: 0.8;
            }}
            @keyframes fadeIn {{
                from {{opacity: 0; transform: translateY(10px);}}
                to {{opacity: 1; transform: translateY(0);}}
            }}
        </style>
        <script>
            window.addEventListener('DOMContentLoaded', () => {{
                const ua = navigator.userAgent.toLowerCase();
                if(ua.includes("discord")) {{
                    document.getElementById("inapp-hint").style.display = "block";
                }}
            }});
        </script>
    </head>
    <body>
        <div class="card">
            <h1>{status_text}</h1>
            <p>{sub_message}</p>
            <p>Twoje konto ma {days_old} dni.</p>
            <a href="{button_link}" class="button">{button_text}</a>
            <div id="inapp-hint" class="hint" style="display:none;">
                ℹ️ Jeśli widzisz pasek Discorda, kliknij ⋮ i wybierz <b>"Otwórz w przeglądarce"</b>.
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route("/status/<user_id>")
def status(user_id):
    db = load_data()
    return jsonify({"verified": db.get(user_id, {}).get("verified", False)})

# Start lokalny
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
