from flask import Flask, request, redirect, jsonify, send_from_directory
from dotenv import load_dotenv
import os
import json
from datetime import datetime
import requests
from urllib.parse import quote_plus
import psycopg2
from psycopg2.extras import DictCursor

# ---------------- CONFIG ----------------
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

DATA_FILE = "verific_data.json"
REDIRECT_URI = f"{BACKEND_URL}/callback"

if not CLIENT_ID or not CLIENT_SECRET or not BACKEND_URL or not DATABASE_URL:
    raise RuntimeError("❌ Brak wymaganych zmiennych środowiskowych!")

# ---------------- DB ----------------
db_conn = psycopg2.connect(DATABASE_URL, sslmode="require", cursor_factory=DictCursor)
db_cur = db_conn.cursor()
db_cur.execute("""
CREATE TABLE IF NOT EXISTS coins (
    user_id BIGINT PRIMARY KEY,
    balance BIGINT DEFAULT 0
);
""")
db_conn.commit()

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ---------------- FLASK ----------------
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
        f"client_id={CLIENT_ID}&redirect_uri={encoded_redirect}"
        f"&response_type=code&scope=identify&state={token}"
    )
    return redirect(oauth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state_token = request.args.get("state")
    if not code:
        return "❌ Brak kodu", 400

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

    headers = {"Authorization": f"Bearer {access_token}"}
    user = requests.get("https://discord.com/api/users/@me", headers=headers, timeout=5).json()

    user_id = int(user["id"])
    account_ts = ((user_id >> 22) + 1420070400000) / 1000
    days_old = (datetime.utcnow() - datetime.utcfromtimestamp(account_ts)).days

    db = load_data()
    verified_status = days_old >= 3
    db[state_token] = {
        "discord_id": str(user_id),
        "username": f"{user['username']}#{user['discriminator']}",
        "days_old": days_old,
        "verified": verified_status
    }
    save_data(db)

    if verified_status:
        db_cur.execute("""
            INSERT INTO coins (user_id, balance) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET balance = coins.balance + EXCLUDED.balance
        """, (user_id, 200))
        db_conn.commit()

    status_text = "✅ Weryfikacja zakończona!" if verified_status else "⛔ Konto za młode!"
    status_color = "#4CAF50" if verified_status else "#ff5252"
    sub_message = "🎉 Witamy na pokładzie!" if verified_status else "Spróbuj ponownie za kilka dni."

    # HTML z księżycem i auto-zamykaniem po 10s
    html = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Weryfikacja Discord</title>
        <style>
            html, body {{margin: 0; padding: 0; height: 100%; color: #fff; font-family: 'Segoe UI', sans-serif; overflow: hidden;}}
            body {{
                background: linear-gradient(135deg, #020024, #090979, #000000);
                background-size: 400% 400%;
                animation: bgMove 30s ease infinite;
            }}
            @keyframes bgMove {{0%{{background-position:0% 50%;}}50%{{background-position:100% 50%;}}100%{{background-position:0% 50%;}}}}
            #stars {{position: fixed; top:0; left:0; width:100%; height:100%; z-index:-2;}}
            .moon {{
                position: fixed; top: 40px; left: 40px;
                width: 100px; height: 100px;
                background: radial-gradient(circle at 30% 30%, #fdfce5, #d4d2c6);
                border-radius: 50%;
                box-shadow: 0 0 30px #fdfce5aa;
                animation: moonPulse 5s infinite;
                z-index: -1;
            }}
            @keyframes moonPulse {{
                0%, 100% {{ transform: scale(1); box-shadow:0 0 25px #fdfce5aa; }}
                50% {{ transform: scale(1.05); box-shadow:0 0 45px #fdfce5; }}
            }}
            .card {{
                position:absolute; top:50%; left:50%;
                transform:translate(-50%,-50%);
                background:rgba(0,0,0,0.4);
                padding:40px; border-radius:15px;
                text-align:center;
                box-shadow:0 15px 35px rgba(0,0,0,0.7);
                max-width:450px; width:90%;
                backdrop-filter:blur(8px);
            }}
            h1 {{color:{status_color}; font-size:2em; margin-bottom:15px;}}
            p {{font-size:1.1em; margin-bottom:20px;}}
            .button {{
                display:block; background:linear-gradient(90deg, #00d2ff, #3a7bd5);
                color:white; padding:14px 25px; border-radius:50px;
                text-decoration:none; font-weight:bold;
                margin:10px auto; max-width:260px;
                box-shadow:0 0 15px rgba(59,173,227,0.6);
            }}
            .button-secondary {{background:linear-gradient(90deg, #757f9a, #d7dde8); color:black;}}
        </style>
    </head>
    <body>
        <canvas id="stars"></canvas>
        <div class="moon"></div>
        <div class="card">
            <h1>{status_text}</h1>
            <p>{sub_message}</p>
            <p>Twoje konto ma {days_old} dni.</p>
            <a href="https://discord.com/app" class="button">Otwórz Discorda</a>
            <a href="javascript:void(0)" onclick="window.close();window.location.href='https://discord.com/app';" class="button button-secondary">❌ Zamknij stronę</a>
        </div>
        <script>
            // Gwiazdki
            const c=document.getElementById('stars'),ctx=c.getContext('2d');
            let stars=[],num=150;
            function resize(){{c.width=innerWidth;c.height=innerHeight;}}resize();window.onresize=resize;
            for(let i=0;i<num;i++)stars.push({x:Math.random()*c.width,y:Math.random()*c.height,r:Math.random()*1.5,s:Math.random()*0.3+0.05,a:Math.random(),t:Math.random()*0.05+0.02});
            function draw(){ctx.clearRect(0,0,c.width,c.height);stars.forEach(s=>{{ctx.beginPath();ctx.globalAlpha=s.a;ctx.arc(s.x,s.y,s.r,0,Math.PI*2);ctx.fillStyle='white';ctx.fill();}});}
            function update(){stars.forEach(s=>{{s.y+=s.s;if(s.y>c.height){{s.x=Math.random()*c.width;s.y=0;}}s.a+=s.t*(Math.random()>.5?1:-1);if(s.a<0.1)s.a=0.1;if(s.a>1)s.a=1;}});}
            (function anim(){{draw();update();requestAnimationFrame(anim);}})();

            // Zamknięcie strony po 10 sekundach
            setTimeout(() => {{
                window.close();
                window.location.href = "https://discord.com/app";
            }}, 10000);
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
