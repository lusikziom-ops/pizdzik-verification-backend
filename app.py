from flask import Flask, request, redirect, jsonify, send_from_directory
from dotenv import load_dotenv
import os
import json
from datetime import datetime
import requests
from urllib.parse import quote_plus

# === ŁADOWANIE ENV ===
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")
DATA_FILE = "verific_data.json"
REDIRECT_URI = f"{BACKEND_URL}/callback"

if not CLIENT_ID or not CLIENT_SECRET or not BACKEND_URL:
    raise RuntimeError("❌ Brak wymaganych zmiennych środowiskowych!")

# === JSON fallback ===
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# === APP ===
app = Flask(__name__, static_url_path='/static')

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

    # TOKEN
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

    # Dane użytkownika
    headers = {"Authorization": f"Bearer {access_token}"}
    user = requests.get(
        "https://discord.com/api/users/@me",
        headers=headers,
        timeout=5
    ).json()

    user_id = int(user["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    # Zapis
    db = load_data()
    verified_status = days_old >= 3
    db[state_token] = {
        "discord_id": str(user_id),
        "username": f"{user['username']}#{user['discriminator']}",
        "days_old": days_old,
        "verified": verified_status
    }
    save_data(db)

    # Wygląd strony
    if verified_status:
        status_text = "✅ Weryfikacja zakończona!"
        status_color = "#4CAF50"
        button_text = "Wejdź na serwer"
        button_link = "https://discord.gg/p8uyQxZ8YZ"
        sub_message = "Twoje konto jest wystarczająco stare. Witamy na pokładzie!"
        auto_redirect = f'<meta http-equiv="refresh" content="8; url={button_link}">'
    else:
        status_text = "⛔ Twoje konto jest za młode!"
        status_color = "#d9534f"
        button_text = "Wróć na Discorda"
        button_link = "https://discord.com/app"
        sub_message = "Spróbuj ponownie za kilka dni, gdy konto będzie starsze."
        auto_redirect = ""

    # --- HTML ---
    html = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Weryfikacja Discord</title>
        {auto_redirect}
        <style>
            @keyframes fadeInUp {{
                0% {{ opacity: 0; transform: translateY(30px); }}
                100% {{ opacity: 1; transform: translateY(0); }}
            }}
            @keyframes pulse {{
                0% {{ transform: scale(1); box-shadow: 0 0 0 rgba(255,255,255,0.6); }}
                50% {{ transform: scale(1.05); box-shadow: 0 0 20px {status_color}; }}
                100% {{ transform: scale(1); box-shadow: 0 0 0 rgba(255,255,255,0.6); }}
            }}
            @keyframes bgZoom {{
                0% {{ background-size: 100%; }}
                50% {{ background-size: 105%; }}
                100% {{ background-size: 100%; }}
            }}
            body {{
                margin: 0;
                height: 100vh;
                font-family: 'Segoe UI', Arial, sans-serif;
                background: linear-gradient(rgba(0,0,0,0.75), rgba(0,0,0,0.75)),
                            url('/static/nocne-rozkminy.jpg') center/cover no-repeat;
                background-attachment: fixed;
                animation: bgZoom 12s infinite ease-in-out;
                display: flex;
                justify-content: center;
                align-items: center;
                color: #fff;
            }}
            .card {{
                background: rgba(255, 255, 255, 0.12);
                padding: 40px;
                border-radius: 15px;
                text-align: center;
                box-shadow: 0 15px 40px rgba(0,0,0,0.7);
                max-width: 450px;
                width: 90%;
                backdrop-filter: blur(12px);
                animation: fadeInUp 0.8s ease-out;
                transition: transform 0.3s ease;
            }}
            .card:hover {{
                transform: translateY(-5px) scale(1.02);
            }}
            h1 {{
                color: {status_color};
                margin-bottom: 15px;
                font-size: 2.2em;
                background: linear-gradient(90deg, {status_color}, #ffffff);
                -webkit-background-clip: text;
                color: transparent;
            }}
            p {{
                font-size: 1.1em;
                margin-bottom: 20px;
                opacity: 0.95;
            }}
            .button {{
                display: block;
                background: {status_color};
                padding: 14px 25px;
                font-size: 1.1em;
                border-radius: 8px;
                color: #fff;
                text-decoration: none;
                font-weight: bold;
                margin: 10px auto;
                max-width: 260px;
                transition: transform 0.2s ease;
                animation: pulse 2s infinite;
            }}
            .button:hover {{
                transform: scale(1.08);
            }}
            .button-secondary {{
                background: #666;
                animation: none;
            }}
            .button-secondary:hover {{
                background: #888;
            }}
            .hint {{
                margin-top: 15px;
                font-size: 0.9em;
                opacity: 0.8;
            }}
        </style>
        <script>
            window.addEventListener('DOMContentLoaded', () => {{
                const ua = navigator.userAgent.toLowerCase();
                if(ua.includes("discord")) {{
                    document.getElementById("inapp-hint").style.display = "block";
                }}
            }});
            function zamknijStrone() {{
                window.close();
                window.location.href = "https://discord.com/app";
            }}
        </script>
    </head>
    <body>
        <div class="card">
            <h1>{status_text}</h1>
            <p>{sub_message}</p>
            <p>Twoje konto ma {days_old} dni.</p>
            <a href="{button_link}" class="button">{button_text}</a>
            <a href="javascript:void(0)" onclick="zamknijStrone()" class="button button-secondary">❌ Zamknij stronę</a>
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
