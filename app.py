from flask import Flask, request, jsonify, render_template_string, send_from_directory
import sqlite3
import secrets
import random
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# === CONFIGURATION ===
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "default-key-change-me")
RATE_LIMIT_HOURS = 24
DB_FILE = 'requests.db'
HISTORY_DB_FILE = 'history.db'
MIN_AMOUNT = 0.1
MAX_AMOUNT = 20.0
STEP = 0.1

# === DATABASE INITIALIZATION ===
def init_db():
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

# === RANDOM AMOUNT WITH WEIGHTED DISTRIBUTION ===
def random_amount_weighted():
    """
    Phân phối xác suất:
    - 70%: 1 - 10 DUCO
    - 20%: 10 - 15 DUCO
    - 10%: 15 - 20 DUCO
    """
    rand = random.random()  # 0.0 -> 1.0
    
    if rand < 0.70:  # 70% - Normal range
        # 1.0 to 10.0 (step 0.1)
        steps = int((10.0 - 1.0) / STEP)
        rand_step = random.randint(0, steps)
        amount = round(1.0 + rand_step * STEP, 1)
        
    elif rand < 0.90:  # 20% - Medium range
        # 10.0 to 15.0 (step 0.1)
        steps = int((15.0 - 10.0) / STEP)
        rand_step = random.randint(0, steps)
        amount = round(10.0 + rand_step * STEP, 1)
        
    else:  # 10% - High range
        # 15.0 to 20.0 (step 0.1)
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

# === ADS.TXT ROUTE ===
@app.route("/ads.txt")
def serve_ads_txt():
    return send_from_directory('.', 'ads.txt', mimetype='text/plain')

# === DISCORD DOMAIN VERIFICATION ===
@app.route("/.well-known/discord")
def discord_verification():
    """
    Discord domain verification
    https://duco-faucet-wgha.onrender.com/.well-known/discord
    """
    # Nội dung xác minh từ Discord
    return "dh=069f0db11d93b4c5b9c8ee695c3f076ae72c3734", 200, {'Content-Type': 'text/plain'}

# === PUBLIC API ===
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

# === ADMIN API ===
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
    c.execute('SELECT username, amount, ip FROM requests WHERE id = ?', (request_id,))
    row = c.fetchone()
    
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

# === WEB INTERFACE ===
HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>DUCO Faucet</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: -apple-system, 'Segoe UI', system-ui, BlinkMacSystemFont, 'Helvetica Neue', sans-serif;
            background: linear-gradient(135deg, #0f212e 0%, #0a1620 100%);
            color: #eef4ff;
            padding: 16px;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            width: 100%;
        }
        
        .header {
            text-align: center;
            margin-bottom: 28px;
            padding: 0 8px;
        }
        
        h1 {
            font-size: clamp(1.8rem, 6vw, 2.5rem);
            font-weight: 700;
            background: linear-gradient(135deg, #f9d976, #f39f86);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            justify-content: center;
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
        
        .probability-note {
            background: #1e2a3a;
            padding: 8px 16px;
            border-radius: 40px;
            font-size: 0.7rem;
            color: #fbbf24;
            margin-top: 12px;
            display: inline-block;
        }
        
        .sub {
            color: #94a3b8;
            margin-top: 8px;
            font-size: 0.85rem;
        }
        
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
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        @media (min-width: 540px) {
            .form-group {
                flex-direction: row;
                align-items: center;
            }
        }
        
        input {
            flex: 2;
            background: #1e2a3a;
            border: 1px solid #334155;
            color: white;
            padding: 14px 18px;
            border-radius: 60px;
            font-size: 1rem;
            width: 100%;
            outline: none;
            transition: all 0.2s;
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
            white-space: nowrap;
            width: 100%;
        }
        
        @media (min-width: 540px) {
            button {
                width: auto;
            }
        }
        
        button:hover {
            transform: scale(1.02);
            background: linear-gradient(95deg, #fcd34d, #f59e0b);
        }
        
        button:active {
            transform: scale(0.98);
        }
        
        button:disabled {
            opacity: 0.6;
            transform: none;
            cursor: not-allowed;
        }
        
        .result {
            margin-top: 16px;
            background: #0f172a80;
            border-radius: 20px;
            padding: 14px;
            font-size: 0.85rem;
            word-break: break-word;
            border-left: 3px solid #fbbf24;
        }
        
        .history-wrapper {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            margin-top: 12px;
            border-radius: 20px;
        }
        
        .history-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            min-width: 320px;
        }
        
        .history-table th,
        .history-table td {
            padding: 12px 10px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        
        .history-table th {
            background: rgba(251, 191, 36, 0.12);
            color: #fbbf24;
            font-weight: 600;
            font-size: 0.8rem;
        }
        
        .amount-badge {
            background: #fbbf24;
            color: #0f172a;
            padding: 4px 10px;
            border-radius: 40px;
            font-size: 0.75rem;
            font-weight: 700;
            display: inline-block;
            white-space: nowrap;
        }
        
        .time-cell {
            font-size: 0.75rem;
            color: #9ca3af;
        }
        
        .footer {
            text-align: center;
            margin-top: 32px;
            font-size: 0.7rem;
            color: #5b6e8c;
            padding: 16px;
        }
        
        .success {
            color: #34d399;
        }
        
        .error {
            color: #f87171;
        }
        
        .loading {
            text-align: center;
            padding: 32px;
            color: #9ca3af;
        }
        
        @media (max-width: 480px) {
            body {
                padding: 12px;
            }
            .card {
                padding: 16px;
            }
            .history-table th,
            .history-table td {
                padding: 8px 6px;
            }
            .amount-badge {
                padding: 2px 8px;
                font-size: 0.7rem;
            }
            .time-cell {
                font-size: 0.65rem;
            }
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>💰 DUCO Faucet <span class="badge">Random 0.1–20</span></h1>
        <div class="probability-note">📊 Distribution: 70% (1-10) | 20% (10-15) | 10% (15-20)</div>
        <div class="sub">Free DUCO every day · Random amount · 1 claim per username per day</div>
    </div>

    <div class="card">
        <h2>📥 Claim DUCO</h2>
        <div class="form-group">
            <input type="text" id="username" placeholder="Duino-Coin Username (e.g., Nam2010)" autocomplete="off">
            <button id="sendReqBtn">🎁 Claim Now</button>
        </div>
        <div id="sendResult" class="result"></div>
    </div>

    <div class="card">
        <h2>📜 Claim History</h2>
        <div id="historyContent" class="loading">⏳ Loading...</div>
    </div>

    <div class="footer">
        ⚡ 1 claim per username per day · Distribution: 70% (1-10) | 20% (10-15) | 10% (15-20)
    </div>
</div>

<script>
    const baseUrl = window.location.origin;

    const sendBtn = document.getElementById('sendReqBtn');
    const usernameInput = document.getElementById('username');
    const sendResult = document.getElementById('sendResult');
    const historyDiv = document.getElementById('historyContent');

    const STORAGE_KEY = 'duco_faucet_username';

    function saveUsername(username) {
        if (username) {
            localStorage.setItem(STORAGE_KEY, username);
        }
    }

    function getSavedUsername() {
        return localStorage.getItem(STORAGE_KEY) || '';
    }

    function formatTime(dateString) {
        if (!dateString) return 'Unknown';
        try {
            const date = new Date(dateString);
            if (isNaN(date.getTime())) return 'Unknown';
            return date.toLocaleString('en-US', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        } catch (e) {
            return 'Unknown';
        }
    }

    function loadSavedUsername() {
        const savedUsername = getSavedUsername();
        if (savedUsername) {
            usernameInput.value = savedUsername;
        }
    }

    async function sendRequest() {
        let username = usernameInput.value.trim();
        if (!username) {
            alert('Please enter your Duino-Coin username');
            return;
        }

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
                sendResult.innerHTML = `
                    <span class="success">✅ Request successful!</span><br>
                    🎲 Amount: <strong class="amount-badge">${data.amount} DUCO</strong><br>
                    🆔 ID: <code>${data.request_id}</code><br>
                    ⏳ Pending approval, will be processed shortly
                `;
                loadHistory();
            } else {
                sendResult.innerHTML = `<span class="error">❌ ${data.error || 'An error occurred'}</span>`;
            }
        } catch (err) {
            sendResult.innerHTML = `<span class="error">❌ Connection error: ${err.message}</span>`;
        } finally {
            sendBtn.disabled = false;
            sendBtn.textContent = '🎁 Claim Now';
        }
    }

    async function loadHistory() {
        try {
            const res = await fetch(`${baseUrl}/history`);
            const data = await res.json();

            if (data.success && data.history && data.history.length > 0) {
                let html = `<div class="history-wrapper"><table class="history-table">
                    <thead>
                        <tr>
                            <th>Username</th>
                            <th>Amount</th>
                            <th>Claim Time</th>
                        </tr>
                    </thead>
                    <tbody>`;
                for (const item of data.history) {
                    const timeStr = formatTime(item.received_at);
                    html += `
                        <tr>
                            <td><strong>${escapeHtml(item.username)}</strong></td>
                            <td><span class="amount-badge">${item.amount} DUCO</span></td>
                            <td class="time-cell">${timeStr}</td>
                        </tr>
                    `;
                }
                html += `</tbody>
                </table></div>`;
                historyDiv.innerHTML = html;
            } else {
                historyDiv.innerHTML = '<p style="text-align:center; color:#6b7280;">📭 No claim history yet.</p>';
            }
        } catch (e) {
            console.error('Error loading history:', e);
            historyDiv.innerHTML = '<p class="error">❌ Failed to load history</p>';
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }

    loadSavedUsername();

    sendBtn.addEventListener('click', sendRequest);
    usernameInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendRequest(); });

    loadHistory();
    setInterval(loadHistory, 35000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

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

# === CORS ===
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
