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

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

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
    db[token] = {"verified": False, "ip": request.remote_addr, "init": str(datetime.utcnow())}
    save_data(db)
    encoded_redirect = quote_plus(REDIRECT_URI)
    oauth_url = (
        f"https://discord.com/api/oauth2/authorize?"
        f"client_id={CLIENT_ID}&redirect_uri={encoded_redirect}&response_type=code&scope=identify&state={token}"
    )
    return redirect(oauth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state_token = request.args.get("state")
    if not code:
        return "❌ Brak kodu", 400

    # TOKEN exchange
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    tokens = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers, timeout=5).json()
    access_token = tokens.get("access_token")
    if not access_token:
        return "❌ Błąd OAuth", 400

    # User info
    headers = {"Authorization": f"Bearer {access_token}"}
    user = requests.get("https://discord.com/api/users/@me", headers=headers, timeout=5).json()
    user_id = int(user["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    # Save result
    db = load_data()
    verified_status = days_old >= 3
    db[state_token] = {
        "discord_id": str(user_id),
        "username": f"{user['username']}#{user['discriminator']}",
        "days_old": days_old,
        "verified": verified_status
    }
    save_data(db)

    # Page content setup
    if verified_status:
        status_text = "✅ Weryfikacja zakończona!"
        status_color = "#4CAF50"
        button_text = "Otwórz Discorda"
        button_link = "https://discord.com/app"
        sub_message = "Twoje konto jest wystarczająco stare. Witamy na pokładzie!"
        auto_redirect = f'<meta http-equiv="refresh" content="8; url={button_link}">'
    else:
        status_text = "⛔ Twoje konto jest za młode!"
        status_color = "#ff5252"
        button_text = "Wróć na Discorda"
        button_link = "https://discord.com/app"
        sub_message = "Spróbuj ponownie za kilka dni, gdy konto będzie starsze."
        auto_redirect = ""

    # HTML with deep navy gradient + visible stars
    html = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Weryfikacja Discord</title>
        {auto_redirect}
        <style>
            html, body {{
                margin: 0; padding: 0; height: 100%;
                font-family: 'Segoe UI', Arial, sans-serif;
                color: #fff; overflow: hidden;
            }}
            body {{
                background: linear-gradient(135deg, #020024, #090979, #000000);
                background-size: 400% 400%;
                animation: bgMove 30s ease infinite;
            }}
            @keyframes bgMove {{
                0% {{ background-position: 0% 50%; }}
                50% {{ background-position: 100% 50%; }}
                100% {{ background-position: 0% 50%; }}
            }}
            #stars {{
                position: fixed;
                top: 0; left: 0;
                width: 100%; height: 100%;
                z-index: -1;
            }}
            .card {{
                position: absolute;
                top: 50%; left: 50%;
                transform: translate(-50%, -50%);
                background: rgba(0,0,0,0.4);
                padding: 40px;
                border-radius: 15px;
                text-align: center;
                box-shadow: 0 15px 35px rgba(0,0,0,0.7);
                max-width: 450px; width: 90%;
                backdrop-filter: blur(8px);
                animation: fadeInUp 0.8s ease-out;
            }}
            @keyframes fadeInUp {{
                0% {{opacity: 0; transform: translate(-50%, calc(-50% + 30px));}}
                100% {{opacity: 1; transform: translate(-50%, -50%);}}
            }}
            h1 {{ color: {status_color}; font-size: 2.2em; margin-bottom: 15px; }}
            p {{ font-size: 1.1em; margin-bottom: 20px; }}
            .button {{
                display: block;
                background: linear-gradient(90deg, #00d2ff, #3a7bd5);
                background-size: 200% auto;
                color: white;
                padding: 14px 25px;
                font-size: 1.1em;
                border-radius: 50px;
                text-decoration: none;
                font-weight: bold;
                margin: 10px auto;
                max-width: 260px;
                box-shadow: 0 0 15px rgba(59,173,227,0.6);
                transition: all 0.4s ease;
            }}
            .button:hover {{ transform: scale(1.07); box-shadow: 0 0 25px rgba(59,173,227,0.9); }}
            .button-secondary {{
                background: linear-gradient(90deg, #757f9a, #d7dde8);
                color: #000;
            }}
        </style>
    </head>
    <body>
        <canvas id="stars"></canvas>
        <div class="card">
            <h1>{status_text}</h1>
            <p>{sub_message}</p>
            <p>Twoje konto ma {days_old} dni.</p>
            <a href="{button_link}" class="button">{button_text}</a>
            <a href="javascript:void(0)" onclick="window.close();window.location.href='https://discord.com/app';" class="button button-secondary">❌ Zamknij stronę</a>
            <div id="inapp-hint" style="margin-top:15px; font-size:0.9em; opacity:0.8; display:none;">
                ℹ️ Jeśli widzisz pasek Discorda, kliknij ⋮ i wybierz <b>"Otwórz w przeglądarce"</b>.
            </div>
        </div>
        <script>
            const ua = navigator.userAgent.toLowerCase();
            if(ua.includes("discord")) {{
                document.getElementById("inapp-hint").style.display = "block";
            }}
            const canvas = document.getElementById('stars');
            const ctx = canvas.getContext('2d');
            let stars = [];
            const numStars = 150;

            function initStars() {{
                canvas.width = window.innerWidth;
                canvas.height = window.innerHeight;
                stars = [];
                for(let i=0;i<numStars;i++) {{
                    stars.push({{
                        x: Math.random()*canvas.width,
                        y: Math.random()*canvas.height,
                        radius: Math.random()*1.5,
                        speed: Math.random()*0.3+0.05,
                        alpha: Math.random(),
                        twinkle: Math.random()*0.05+0.02
                    }});
                }}
            }}
            function drawStars() {{
                ctx.clearRect(0,0,canvas.width,canvas.height);
                stars.forEach(star => {{
                    ctx.beginPath();
                    ctx.globalAlpha = star.alpha;
                    ctx.arc(star.x, star.y, star.radius, 0, Math.PI*2);
                    ctx.fillStyle = "white";
                    ctx.fill();
                }});
                ctx.globalAlpha = 1;
            }}
            function updateStars() {{
                stars.forEach(star => {{
                    star.y += star.speed;
                    if(star.y > canvas.height) {{
                        star.x = Math.random()*canvas.width;
                        star.y = 0;
                    }}
                    star.alpha += star.twinkle * (Math.random() > 0.5 ? 1 : -1);
                    if(star.alpha < 0.1) star.alpha = 0.1;
                    if(star.alpha > 1) star.alpha = 1;
                }});
            }}
            function animate() {{
                drawStars();
                updateStars();
                requestAnimationFrame(animate);
            }}
            window.addEventListener('resize', initStars);
            initStars();
            animate();
        </script>
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
