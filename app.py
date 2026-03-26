from flask import Flask, request, jsonify, render_template_string, send_from_directory
import sqlite3
import secrets
import random
import os
import time
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

# === CONFIGURATION ===
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "default-key-change-me")
RATE_LIMIT_HOURS = 24
DB_FILE = 'requests.db'
HISTORY_DB_FILE = 'history.db'
STATS_DB_FILE = 'stats.db'
MIN_AMOUNT = 0.1
MAX_AMOUNT = 20.0
STEP = 0.1

# === FAUCET BALANCE CACHE ===
faucet_balance_cache = {
    "balance": None,
    "last_updated": None,
    "expiry_seconds": 60
}

# === DATABASE INITIALIZATION ===
def init_db():
    # Requests database
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS requests
                 (id TEXT PRIMARY KEY,
                  username TEXT,
                  ip TEXT,
                  created_at TIMESTAMP,
                  amount REAL,
                  status TEXT)''')
    conn.commit()
    conn.close()
    
    # History database
    conn = sqlite3.connect(HISTORY_DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  amount REAL,
                  received_at TIMESTAMP,
                  ip TEXT)''')
    conn.commit()
    conn.close()
    
    # Stats database (visits and total DUCO)
    conn = sqlite3.connect(STATS_DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (key TEXT PRIMARY KEY,
                  value INTEGER DEFAULT 0)''')
    
    # Initialize counters if not exist
    c.execute('INSERT OR IGNORE INTO stats (key, value) VALUES ("total_visits", 0)')
    c.execute('INSERT OR IGNORE INTO stats (key, value) VALUES ("total_duco", 0)')
    conn.commit()
    conn.close()

init_db()

# === CREATE ADS.TXT FILE ===
def create_ads_txt():
    ads_content = """# Google AdSense
google.com, pub-XXXXXXXXXXXXXXXX, DIRECT, f08c47fec0942fa0
"""
    if not os.path.exists('ads.txt'):
        with open('ads.txt', 'w', encoding='utf-8') as f:
            f.write(ads_content)

create_ads_txt()

# === STATISTICS FUNCTIONS ===
def increment_visits():
    conn = sqlite3.connect(STATS_DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE stats SET value = value + 1 WHERE key = "total_visits"')
    conn.commit()
    conn.close()

def add_to_total_duco(amount):
    conn = sqlite3.connect(STATS_DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE stats SET value = value + ? WHERE key = "total_duco"', (int(amount * 10),))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(STATS_DB_FILE)
    c = conn.cursor()
    c.execute('SELECT key, value FROM stats')
    rows = c.fetchall()
    conn.close()
    
    stats = {}
    for key, value in rows:
        if key == "total_duco":
            stats[key] = value / 10.0
        else:
            stats[key] = value
    return stats

# === FAUCET BALANCE FUNCTIONS ===
def get_faucet_balance():
    """Lấy số dư faucet với cache 1 phút"""
    global faucet_balance_cache
    
    now = datetime.now()
    if (faucet_balance_cache["balance"] is not None and 
        faucet_balance_cache["last_updated"] is not None and
        (now - faucet_balance_cache["last_updated"]).total_seconds() < faucet_balance_cache["expiry_seconds"]):
        return faucet_balance_cache["balance"]
    
    try:
        FAUCET_USERNAME = os.environ.get("FAUCET_USERNAME", "Nam2010")
        url = f"https://server.duinocoin.com/users/{FAUCET_USERNAME}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                balance = data["result"]["balance"]["balance"]
                faucet_balance_cache["balance"] = round(balance, 2)
                faucet_balance_cache["last_updated"] = now
                return faucet_balance_cache["balance"]
    except Exception as e:
        print(f"Error fetching faucet balance: {e}")
    
    return faucet_balance_cache["balance"] or 0

# === RANDOM AMOUNT WITH WEIGHTED DISTRIBUTION ===
def random_amount_weighted():
    rand = random.random()
    
    if rand < 0.70:
        steps = int((10.0 - 1.0) / STEP)
        rand_step = random.randint(0, steps)
        amount = round(1.0 + rand_step * STEP, 1)
    elif rand < 0.90:
        steps = int((15.0 - 10.0) / STEP)
        rand_step = random.randint(0, steps)
        amount = round(10.0 + rand_step * STEP, 1)
    else:
        steps = int((20.0 - 15.0) / STEP)
        rand_step = random.randint(0, steps)
        amount = round(15.0 + rand_step * STEP, 1)
    
    return amount

# === HELPER FUNCTIONS ===
def get_db():
    return sqlite3.connect(DB_FILE)

def get_history_db():
    return sqlite3.connect(HISTORY_DB_FILE)

def add_to_history(username, amount, ip):
    conn = get_history_db()
    c = conn.cursor()
    c.execute('''INSERT INTO history (username, amount, received_at, ip)
                 VALUES (?, ?, ?, ?)''',
              (username, amount, datetime.now().isoformat(), ip))
    conn.commit()
    conn.close()
    add_to_total_duco(amount)

# === ROUTES ===
@app.route("/ads.txt")
def serve_ads_txt():
    return send_from_directory('.', 'ads.txt', mimetype='text/plain')

@app.route("/.well-known/discord")
def discord_verification():
    return "dh=069f0db11d93b4c5b9c8ee695c3f076ae72c3734", 200, {'Content-Type': 'text/plain'}

@app.route("/api/stats", methods=["GET"])
def get_stats_api():
    stats = get_stats()
    return jsonify({
        "success": True,
        "total_visits": stats.get("total_visits", 0),
        "total_duco": stats.get("total_duco", 0)
    })

@app.route("/api/faucet-balance", methods=["GET"])
def get_faucet_balance_api():
    balance = get_faucet_balance()
    return jsonify({
        "success": True,
        "balance": balance,
        "balance_formatted": f"{balance:,.2f} DUCO"
    })

@app.route("/api/update-balance", methods=["POST"])
def update_balance():
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    balance = data.get("balance")
    
    if balance is not None:
        global faucet_balance_cache
        faucet_balance_cache["balance"] = balance
        faucet_balance_cache["last_updated"] = datetime.now()
        return jsonify({"success": True})
    
    return jsonify({"error": "Missing balance"}), 400

@app.route("/request", methods=["POST"])
def submit_request():
    data = request.get_json()
    username = data.get("username")
    if not username:
        return jsonify({"error": "Missing username"}), 400

    ip = request.remote_addr
    cutoff = datetime.now() - timedelta(hours=RATE_LIMIT_HOURS)

    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT COUNT(*) FROM requests
                 WHERE status = 'pending'
                 AND username = ?
                 AND created_at > ?''', (username, cutoff))
    pending_count = c.fetchone()[0]
    
    if pending_count > 0:
        conn.close()
        return jsonify({"error": "You already have a pending request"}), 429
    
    history_conn = get_history_db()
    h = history_conn.cursor()
    h.execute('''SELECT COUNT(*) FROM history
                 WHERE username = ?
                 AND received_at > ?''', (username, cutoff))
    history_count = h.fetchone()[0]
    history_conn.close()
    
    if history_count > 0:
        conn.close()
        return jsonify({"error": "You have already claimed DUCO in the last 24 hours"}), 429

    request_id = secrets.token_hex(8)
    amount = random_amount_weighted()
    c.execute('''INSERT INTO requests (id, username, ip, created_at, amount, status)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (request_id, username, ip, datetime.now().isoformat(), amount, 'pending'))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "request_id": request_id, "amount": amount})

@app.route("/admin/requests", methods=["GET"])
def list_pending():
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, username, ip, created_at, amount FROM requests WHERE status = "pending" ORDER BY created_at')
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "username": r[1], "ip": r[2], "created_at": r[3], "amount": r[4]} for r in rows])

@app.route("/admin/requests/<request_id>", methods=["DELETE"])
def delete_request(request_id):
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM requests WHERE id = ?', (request_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected == 0:
        return jsonify({"error": "Request not found"}), 404
    return jsonify({"success": True})

@app.route("/admin/complete", methods=["POST"])
def complete_transaction():
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    username = data.get("username")
    amount = data.get("amount")
    ip = data.get("ip", "unknown")
    
    if not username or not amount:
        return jsonify({"error": "Missing required fields"}), 400
    
    add_to_history(username, amount, ip)
    return jsonify({"success": True})

@app.route("/history", methods=["GET"])
def get_history():
    conn = sqlite3.connect(HISTORY_DB_FILE)
    c = conn.cursor()
    c.execute('SELECT username, amount, received_at FROM history ORDER BY received_at DESC LIMIT 50')
    rows = c.fetchall()
    conn.close()
    
    history = []
    for row in rows:
        history.append({
            "username": row[0],
            "amount": row[1],
            "received_at": row[2]
        })
    
    return jsonify({"success": True, "history": history})

@app.route("/")
def index():
    increment_visits()
    return render_template_string(HTML_TEMPLATE)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
    return response

# === HTML TEMPLATE ===
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>DUCO Faucet</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, #0f212e 0%, #0a1620 100%);
            color: #eef4ff;
            padding: 16px;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 28px; }
        h1 {
            font-size: clamp(1.8rem, 6vw, 2.5rem);
            background: linear-gradient(135deg, #f9d976, #f39f86);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }
        .stats-grid {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin: 20px 0;
            flex-wrap: wrap;
        }
        .stat-card {
            background: rgba(251, 191, 36, 0.15);
            backdrop-filter: blur(8px);
            border-radius: 20px;
            padding: 16px 24px;
            text-align: center;
            border: 1px solid rgba(251, 191, 36, 0.3);
            min-width: 160px;
            transition: all 0.3s ease;
        }
        .stat-card.low-balance {
            border-color: #f87171;
            background: rgba(248, 113, 113, 0.2);
        }
        .stat-card.critical-balance {
            border-color: #ef4444;
            background: rgba(239, 68, 68, 0.25);
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
            70% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
            100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
        }
        .stat-value {
            font-size: 1.8rem;
            font-weight: 800;
            color: #fbbf24;
        }
        .stat-value.low-balance { color: #f87171; }
        .stat-value.critical-balance { color: #ef4444; }
        .stat-label {
            font-size: 0.75rem;
            color: #94a3b8;
            margin-top: 8px;
        }
        .warning-text {
            font-size: 0.7rem;
            margin-top: 6px;
            color: #f87171;
        }
        .badge {
            background: #10b981;
            padding: 4px 12px;
            border-radius: 40px;
            font-size: 0.75rem;
            font-weight: 600;
            color: white;
            display: inline-block;
        }
        .badge.warning {
            background: #f59e0b;
        }
        .badge.critical {
            background: #ef4444;
            animation: pulse-badge 1s infinite;
        }
        @keyframes pulse-badge {
            0% { opacity: 1; }
            50% { opacity: 0.7; }
            100% { opacity: 1; }
        }
        .probability-note {
            background: #1e2a3a;
            padding: 8px 16px;
            border-radius: 40px;
            font-size: 0.7rem;
            color: #fbbf24;
            margin-top: 12px;
            display: inline-block;
        }
        .sub { color: #94a3b8; margin-top: 8px; font-size: 0.85rem; }
        .card {
            background: rgba(15, 25, 35, 0.7);
            backdrop-filter: blur(12px);
            border-radius: 28px;
            padding: 20px;
            margin-bottom: 24px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .card h2 {
            font-size: 1.4rem;
            margin-bottom: 18px;
            color: #fbbf24;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        @media (min-width: 540px) {
            .form-group { flex-direction: row; align-items: center; }
        }
        input {
            flex: 2;
            background: #1e2a3a;
            border: 1px solid #334155;
            color: white;
            padding: 14px 18px;
            border-radius: 60px;
            font-size: 1rem;
            outline: none;
        }
        input:focus {
            border-color: #fbbf24;
            box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.2);
        }
        button {
            background: linear-gradient(95deg, #fbbf24, #f59e0b);
            border: none;
            color: #0f172a;
            font-weight: 700;
            padding: 14px 24px;
            border-radius: 60px;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.2s;
        }
        button:hover { transform: scale(1.02); }
        button:disabled { opacity: 0.6; transform: none; cursor: not-allowed; }
        .result {
            margin-top: 16px;
            background: #0f172a80;
            border-radius: 20px;
            padding: 14px;
            border-left: 3px solid #fbbf24;
        }
        .history-wrapper { overflow-x: auto; margin-top: 12px; }
        .history-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        .history-table th, .history-table td {
            padding: 12px 10px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        .history-table th {
            background: rgba(251, 191, 36, 0.12);
            color: #fbbf24;
        }
        .amount-badge {
            background: #fbbf24;
            color: #0f172a;
            padding: 4px 10px;
            border-radius: 40px;
            font-size: 0.75rem;
            font-weight: 700;
            display: inline-block;
        }
        .footer {
            text-align: center;
            margin-top: 32px;
            font-size: 0.7rem;
            color: #5b6e8c;
        }
        .success { color: #34d399; }
        .error { color: #f87171; }
        .loading { text-align: center; padding: 32px; color: #9ca3af; }
        @media (max-width: 480px) {
            .stat-card { padding: 12px 16px; min-width: 120px; }
            .stat-value { font-size: 1.2rem; }
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>💰 DUCO Faucet <span class="badge" id="balanceBadge">Random 1–20</span></h1>
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-value" id="totalVisits">0</div><div class="stat-label">Total Visits</div></div>
            <div class="stat-card"><div class="stat-value" id="totalDUCO">0</div><div class="stat-label">DUCO Distributed</div></div>
            <div class="stat-card" id="balanceCard"><div class="stat-value" id="faucetBalance">0</div><div class="stat-label">Faucet Balance</div><div id="balanceWarning" class="warning-text"></div></div>
        </div>
        <div class="probability-note">📊 70% (1-10) | 20% (10-15) | 10% (15-20)</div>
        <div class="sub">Free DUCO every day · 1 claim per username per day</div>
    </div>

    <div class="card">
        <h2>📥 Claim DUCO</h2>
        <div class="form-group">
            <input type="text" id="username" placeholder="Duino-Coin Username" autocomplete="off">
            <button id="sendReqBtn">🎁 Claim Now</button>
        </div>
        <div id="sendResult" class="result"></div>
    </div>

    <div class="card">
        <h2>📜 Claim History</h2>
        <div id="historyContent" class="loading">⏳ Loading...</div>
    </div>

    <div class="footer">⚡ 1 claim per username per day · Distribution: 70% (1-10) | 20% (10-15) | 10% (15-20)</div>
</div>

<script>
    const baseUrl = window.location.origin;
    const sendBtn = document.getElementById('sendReqBtn');
    const usernameInput = document.getElementById('username');
    const sendResult = document.getElementById('sendResult');
    const historyDiv = document.getElementById('historyContent');
    const STORAGE_KEY = 'duco_faucet_username';

    function saveUsername(username) { if (username) localStorage.setItem(STORAGE_KEY, username); }
    function getSavedUsername() { return localStorage.getItem(STORAGE_KEY) || ''; }
    
    // === HIỂN THỊ SỐ ĐẦY ĐỦ (KHÔNG VIẾT TẮT) ===
    function formatNumberFull(num) {
        // Hiển thị số đầy đủ với dấu phẩy phân cách hàng nghìn
        return num.toLocaleString('en-US', {
            minimumFractionDigits: 0,
            maximumFractionDigits: 2
        });
    }
    
    function formatTime(dateString) {
        if (!dateString) return 'Unknown';
        try { return new Date(dateString).toLocaleString(); } catch(e) { return 'Unknown'; }
    }
    function escapeHtml(str) { if (!str) return ''; return str.replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'})[m]); }

    async function loadStats() {
        try {
            const res = await fetch(`${baseUrl}/api/stats`);
            const data = await res.json();
            if (data.success) {
                document.getElementById('totalVisits').textContent = formatNumberFull(data.total_visits);
                document.getElementById('totalDUCO').textContent = formatNumberFull(data.total_duco) + ' DUCO';
            }
        } catch(e) { console.error(e); }
    }

    async function loadFaucetBalance() {
        try {
            const res = await fetch(`${baseUrl}/api/faucet-balance`);
            const data = await res.json();
            if (data.success) {
                const balance = data.balance;
                const el = document.getElementById('faucetBalance');
                const card = document.getElementById('balanceCard');
                const badge = document.getElementById('balanceBadge');
                const warning = document.getElementById('balanceWarning');
                
                // Hiển thị số đầy đủ
                el.textContent = formatNumberFull(balance) + ' DUCO';
                
                // Cập nhật màu sắc và cảnh báo dựa trên số dư
                if (balance < 20) {
                    // Cực kỳ thấp - đỏ, nhấp nháy
                    el.className = 'stat-value critical-balance';
                    card.className = 'stat-card critical-balance';
                    badge.className = 'badge critical';
                    badge.innerHTML = '⚠️ CRITICAL ⚠️';
                    warning.innerHTML = '⚠️ CRITICAL BALANCE! Faucet will stop soon! ⚠️';
                    warning.style.color = '#ef4444';
                } else if (balance < 50) {
                    // Thấp - cam
                    el.className = 'stat-value low-balance';
                    card.className = 'stat-card low-balance';
                    badge.className = 'badge warning';
                    badge.innerHTML = '⚠️ Low Balance';
                    warning.innerHTML = '⚠️ Balance is low, please consider donating!';
                    warning.style.color = '#f59e0b';
                } else if (balance < 100) {
                    // Trung bình thấp
                    el.className = 'stat-value low-balance';
                    card.className = 'stat-card low-balance';
                    badge.className = 'badge';
                    badge.innerHTML = 'Random 1–20';
                    warning.innerHTML = 'Balance: ' + formatNumberFull(balance) + ' DUCO remaining';
                    warning.style.color = '#fbbf24';
                } else {
                    // Bình thường
                    el.className = 'stat-value';
                    card.className = 'stat-card';
                    badge.className = 'badge';
                    badge.innerHTML = 'Random 1–20';
                    warning.innerHTML = '';
                }
            }
        } catch(e) { 
            console.error(e); 
            document.getElementById('faucetBalance').textContent = '? DUCO';
        }
    }

    async function loadHistory() {
        try {
            const res = await fetch(`${baseUrl}/history`);
            const data = await res.json();
            if (data.success && data.history && data.history.length > 0) {
                let html = `<div class="history-wrapper"><table class="history-table"><thead>\
                    <th>Username</th><th>Amount</th><th>Claim Time</th>\
                </thead><tbody>`;
                for (const item of data.history) {
                    html += `<tr>\
                        <td><strong>${escapeHtml(item.username)}</strong></td>\
                        <td><span class="amount-badge">${item.amount} DUCO</span></td>\
                        <td>${formatTime(item.received_at)}</td>\
                    </tr>`;
                }
                html += `</tbody></table></div>`;
                historyDiv.innerHTML = html;
            } else {
                historyDiv.innerHTML = '<p style="text-align:center; color:#6b7280;">📭 No claim history yet.</p>';
            }
        } catch(e) { historyDiv.innerHTML = '<p class="error">❌ Failed to load history</p>'; }
    }

    async function sendRequest() {
        let username = usernameInput.value.trim();
        if (!username) { alert('Please enter your Duino-Coin username'); return; }
        saveUsername(username);
        sendBtn.disabled = true;
        sendBtn.textContent = '⏳ Processing...';
        sendResult.innerHTML = '<span style="color:#fbbf24;">⏳ Sending request...</span>';
        try {
            const res = await fetch(`${baseUrl}/request`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username })
            });
            const data = await res.json();
            if (res.status === 429) {
                sendResult.innerHTML = `<span class="error">❌ ${data.error}</span>`;
            } else if (data.success) {
                sendResult.innerHTML = `<span class="success">✅ Request successful!</span><br>🎲 Amount: <strong class="amount-badge">${data.amount} DUCO</strong><br>🆔 ID: <code>${data.request_id}</code><br>⏳ Pending approval, will be processed shortly`;
                loadHistory();
                loadStats();
                loadFaucetBalance();
            } else {
                sendResult.innerHTML = `<span class="error">❌ ${data.error || 'An error occurred'}</span>`;
            }
        } catch(err) {
            sendResult.innerHTML = `<span class="error">❌ Connection error: ${err.message}</span>`;
        } finally {
            sendBtn.disabled = false;
            sendBtn.textContent = '🎁 Claim Now';
        }
    }

    usernameInput.value = getSavedUsername();
    loadStats();
    loadFaucetBalance();
    loadHistory();
    sendBtn.addEventListener('click', sendRequest);
    usernameInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendRequest(); });
    setInterval(loadStats, 30000);
    setInterval(loadFaucetBalance, 60000);
    setInterval(loadHistory, 35000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
