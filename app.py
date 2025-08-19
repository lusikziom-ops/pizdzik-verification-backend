import os
import json
import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import Flask, request, redirect, jsonify, send_from_directory, make_response
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

import requests
import psycopg2
from psycopg2 import OperationalError, InterfaceError
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

# === ŁADOWANIE ENV ===
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BACKEND_URL = (os.getenv("BACKEND_URL") or "").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL")
TRUST_PROXY = (os.getenv("TRUST_PROXY") or "1").strip().lower() in ("1", "true", "yes", "y", "t")

if not CLIENT_ID or not CLIENT_SECRET or not BACKEND_URL or not DATABASE_URL:
    raise RuntimeError("❌ Brak wymaganych zmiennych środowiskowych: CLIENT_ID, CLIENT_SECRET, BACKEND_URL, DATABASE_URL")

REDIRECT_URI = f"{BACKEND_URL}/callback"

# === Połączenie z PostgreSQL: WĄTKOWA PULA + keepalive ===
db_pool = ThreadedConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=DATABASE_URL,
    sslmode="require",
    connect_timeout=10,
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=5,
    application_name="verify-backend",
)

def db_exec(query: str, params=None, fetch: str | None = None, retries: int = 1):
    """
    Wykonuje zapytanie w transakcji na świeżym połączeniu z puli.
    fetch: None | "one" | "all"
    retries: ile RAZY PONOWIĆ po błędzie połączenia (EOF, zerwanie)
    """
    attempt = 0
    while True:
        attempt += 1
        conn = None
        try:
            conn = db_pool.getconn()
            conn.autocommit = False
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    if fetch == "one":
                        return cur.fetchone()
                    if fetch == "all":
                        return cur.fetchall()
                    return None
        except (OperationalError, InterfaceError):
            # zerwane połączenie – zamknij i ponów
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            if attempt <= (retries + 1):
                continue
            raise
        finally:
            try:
                if conn:
                    db_pool.putconn(conn, close=False)
            except Exception:
                pass

def init_db():
    # coins – saldo użytkownika
    db_exec("""
        CREATE TABLE IF NOT EXISTS coins (
            user_id BIGINT PRIMARY KEY,
            balance BIGINT DEFAULT 0
        );
    """)
    # verifications – status weryfikacji po tokenie
    db_exec("""
        CREATE TABLE IF NOT EXISTS verifications (
            token TEXT PRIMARY KEY,
            discord_id BIGINT,
            username TEXT,
            days_old INT,
            verified BOOLEAN DEFAULT FALSE,
            ip INET,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        );
    """)
    # indeks po user_id dla zapytań statusu „po użytkowniku”
    db_exec("CREATE INDEX IF NOT EXISTS idx_verif_discord_id ON verifications(discord_id);")

init_db()

# === Flask app ===
app = Flask(__name__, static_url_path="/static")
if TRUST_PROXY:
    # ufaj 1 warstwie proxy (X-Forwarded-For, X-Forwarded-Proto)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route("/")
def home():
    return "✅ Backend weryfikacji działa!", 200

# --- Pobranie PEŁNEGO IP klienta (Cloudflare/Proxy-friendly) ---
def _client_ip_full() -> str | None:
    candidates: list[str | None] = []
    # Priorytet: Cloudflare -> X-Real-IP -> pierwszy z X-Forwarded-For -> remote_addr
    candidates.append(request.headers.get("CF-Connecting-IP"))
    candidates.append(request.headers.get("X-Real-IP"))

    xff = request.headers.get("X-Forwarded-For")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            candidates.append(parts[0])  # pierwszy = klient

    candidates.append(request.remote_addr)

    for raw in candidates:
        if not raw:
            continue
        ip = raw

        # Obsługa ewentualnych form "ip:port" lub "[ipv6]:port"
        # IPv4: 1.2.3.4:5678
        if ":" in ip and ip.count(":") == 1 and "." in ip:
            host, _port = ip.split(":", 1)
            ip = host
        # IPv6: [2001:db8::1]:5678
        if ip.startswith("[") and "]" in ip:
            ip = ip[1:ip.index("]")]

        try:
            ipaddress.ip_address(ip)
            return ip
        except ValueError:
            continue
    return None

# --- Pomocnicze: transakcyjna aktualizacja weryfikacji + ewentualna nagroda ---
def update_verification_and_maybe_award(token: str, user_id: int, username: str, days_old: int, verified: bool, ip: str | None):
    """
    Jedna transakcja:
    - odczytaj poprzedni rekord,
    - zaktualizuj/utwórz weryfikację,
    - jeśli verified przechodzi z FALSE->TRUE, dodaj +200 coins (idempotentnie względem kolejnych wywołań).
    """
    conn = None
    try:
        conn = db_pool.getconn()
        conn.autocommit = False
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # odczyt poprzedniego (FOR UPDATE przez aktualizację poniżej)
                cur.execute("SELECT verified FROM verifications WHERE token=%s FOR UPDATE", (token,))
                prev = cur.fetchone()
                prev_verified = bool(prev["verified"]) if prev else False

                # UPSERT weryfikacji (nie nadpisuj istniejącego IP NULL-em)
                cur.execute("""
                    INSERT INTO verifications (token, discord_id, username, days_old, verified, ip, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (token) DO UPDATE SET
                        discord_id = EXCLUDED.discord_id,
                        username   = EXCLUDED.username,
                        days_old   = EXCLUDED.days_old,
                        verified   = EXCLUDED.verified,
                        ip         = COALESCE(EXCLUDED.ip, verifications.ip),
                        updated_at = now();
                """, (token, user_id, username, days_old, verified, ip))

                # NAGRADZAMY TYLKO przy pierwszym przejściu na verified=True
                if verified and not prev_verified:
                    cur.execute("""
                        INSERT INTO coins (user_id, balance) VALUES (%s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET balance = coins.balance + EXCLUDED.balance;
                    """, (user_id, 200))
    finally:
        try:
            if conn:
                db_pool.putconn(conn, close=False)
        except Exception:
            pass

@app.route("/verify")
def verify():
    token = (request.args.get("token") or "").strip()
    if not token:
        return "❌ Brak tokenu", 400
    if len(token) > 256:
        return "❌ Zbyt długi token", 400

    ip_val = _client_ip_full()
    # Wstępna rejestracja tokenu (jeśli nie istnieje) – przydaje się do wczesnej diagnostyki
    db_exec("""
        INSERT INTO verifications (token, ip, created_at, updated_at)
        VALUES (%s, %s, now(), now())
        ON CONFLICT (token) DO UPDATE SET
            ip = COALESCE(EXCLUDED.ip, verifications.ip),
            updated_at = now();
    """, (token, ip_val), fetch=None)

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "state": token,
    }
    oauth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    return redirect(oauth_url, code=302)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state_token = request.args.get("state")
    if not code or not state_token:
        return "❌ Brak code lub state", 400

    # --- Wymiana code -> access_token ---
    try:
        token_resp = requests.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except requests.RequestException as e:
        return f"❌ Błąd połączenia z Discord OAuth: {e}", 502

    if token_resp.status_code != 200:
        try:
            detail = token_resp.json()
        except Exception:
            detail = token_resp.text
        return make_response(f"❌ OAuth nie powiódł się: {detail}", 400)

    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    if not access_token:
        return make_response(f"❌ Brak access_token w odpowiedzi OAuth: {tokens}", 400)

    # --- Dane użytkownika ---
    try:
        user_resp = requests.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    except requests.RequestException as e:
        return f"❌ Błąd pobierania /users/@me: {e}", 502

    if user_resp.status_code != 200:
        return make_response(f"❌ /users/@me zwróciło {user_resp.status_code}: {user_resp.text}", 400)

    try:
        user = user_resp.json()
    except Exception as e:
        return f"❌ Nieprawidłowy JSON użytkownika: {e}", 500

    try:
        user_id = int(user["id"])
    except Exception:
        return "❌ Brak/nieprawidłowe 'id' użytkownika", 500

    # Discord: wyświetlana nazwa może być w global_name, a discriminator bywa '0'
    username = user.get("global_name") or user.get("username") or "Discord User"

    # Obliczenie wieku konta po snowflake (ms od 2015-01-01)
    account_ts = ((user_id >> 22) + 1420070400000) / 1000.0
    created_dt = datetime.fromtimestamp(account_ts, tz=timezone.utc)
    days_old = (datetime.now(tz=timezone.utc) - created_dt).days

    verified_status = days_old >= 3

    # Transakcyjna aktualizacja + ewentualna nagroda (z pełnym IP)
    try:
        ip_val = _client_ip_full()
        update_verification_and_maybe_award(
            token=state_token,
            user_id=user_id,
            username=f"{username}",
            days_old=days_old,
            verified=verified_status,
            ip=ip_val,
        )
    except Exception as e:
        return f"❌ Błąd zapisu do bazy: {e}", 500

    # --- HTML wynikowy ---
    status_text = "✅ Weryfikacja zakończona!" if verified_status else "⛔ Konto za młode!"
    status_color = "#4CAF50" if verified_status else "#ff5252"
    sub_message = "🎉 Witamy na pokładzie!" if verified_status else "Spróbuj ponownie za kilka dni."

    html = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            .card {{position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
                background:rgba(0,0,0,0.4); padding:40px; border-radius:15px; text-align:center;
                box-shadow:0 15px 35px rgba(0,0,0,0.7); max-width:450px; width:90%;
                backdrop-filter:blur(8px);}}
            h1 {{color:{status_color}; font-size:2em; margin-bottom:15px;}}
            p {{font-size:1.1em; margin-bottom:20px;}}
            .button {{display:block; background:linear-gradient(90deg, #00d2ff, #3a7bd5); color:white;
                padding:14px 25px; border-radius:50px; text-decoration:none; font-weight:bold;
                margin:10px auto; max-width:260px; box-shadow:0 0 15px rgba(59,173,227,0.6);}}
            .button-secondary {{background:linear-gradient(90deg, #757f9a, #d7dde8); color:black;}}
        </style>
    </head>
    <body>
        <canvas id="stars"></canvas>
        <div class="card">
            <h1>{status_text}</h1>
            <p>{sub_message}</p>
            <p>Twoje konto ma {days_old} dni.</p>
            <a href="https://discord.com/app" class="button">Otwórz Discorda</a>
            <a href="javascript:void(0)" onclick="window.close();window.location.href='https://discord.com/app';" class="button button-secondary">❌ Zamknij stronę</a>
        </div>
        <script>
            const c=document.getElementById('stars'),ctx=c.getContext('2d');
            let stars=[],num=150;
            function resize(){{c.width=innerWidth;c.height=innerHeight;}}resize();window.onresize=resize;
            for(let i=0;i<num;i++)stars.push({{x:Math.random()*c.width,y:Math.random()*c.height,r:Math.random()*1.5,s:Math.random()*0.3+0.05,a:Math.random(),t:Math.random()*0.05+0.02}});
            function draw(){{ctx.clearRect(0,0,c.width,c.height);stars.forEach(s=>{{ctx.beginPath();ctx.globalAlpha=s.a;ctx.arc(s.x,s.y,s.r,0,Math.PI*2);ctx.fillStyle='white';ctx.fill();}});ctx.globalAlpha=1;}}
            function update(){{stars.forEach(s=>{{s.y+=s.s;if(s.y>c.height){{s.x=Math.random()*c.width;s.y=0;}}s.a+=s.t*(Math.random()>.5?1:-1);if(s.a<0.1)s.a=0.1;if(s.a>1)s.a=1;}});}}
            (function anim(){{draw();update();requestAnimationFrame(anim);}})();
            setTimeout(()=>{{window.close();window.location.href='https://discord.com/app';}},10000);
        </script>
    </body>
    </html>
    """
    resp = make_response(html, 200)
    return resp

# Status po TOKENIE (zalecane do integracji z botem)
@app.route("/status/token/<token>")
def status_token(token):
    row = db_exec("SELECT verified, discord_id, username, days_old, updated_at FROM verifications WHERE token=%s", (token,), fetch="one")
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify({"ok": True, "verified": bool(row["verified"]), "discord_id": row.get("discord_id"), "username": row.get("username"), "days_old": row.get("days_old"), "updated_at": str(row.get("updated_at"))})

# Status po USER_ID (kompatybilność wsteczna)
@app.route("/status/user/<int:user_id>")
def status_user(user_id: int):
    row = db_exec("""
        SELECT verified, token, username, days_old, updated_at
        FROM verifications
        WHERE discord_id=%s
        ORDER BY updated_at DESC
        LIMIT 1
    """, (user_id,), fetch="one")
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify({"ok": True, "verified": bool(row["verified"]), "token": row.get("token"), "username": row.get("username"), "days_old": row.get("days_old"), "updated_at": str(row.get("updated_at"))})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
