from flask import Flask, request, jsonify, render_template_string
import sqlite3
import secrets
import random
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# === CẤU HÌNH ===
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "default-key-change-me")
RATE_LIMIT_HOURS = 24
DB_FILE = 'requests.db'
MIN_AMOUNT = 0.1
MAX_AMOUNT = 20.0
STEP = 0.1  # bước nhảy

# === KHỞI TẠO DATABASE ===
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

init_db()

# === HELPER ===
def get_db():
    return sqlite3.connect(DB_FILE)

def random_amount():
    """Tạo số lượng ngẫu nhiên từ MIN_AMOUNT đến MAX_AMOUNT, bước STEP"""
    steps = int((MAX_AMOUNT - MIN_AMOUNT) / STEP)
    rand_step = random.randint(0, steps)
    return round(MIN_AMOUNT + rand_step * STEP, 1)

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
                 AND (ip = ? OR username = ?)
                 AND created_at > ?''', (ip, username, cutoff))
    count = c.fetchone()[0]
    if count > 0:
        conn.close()
        return jsonify({"error": "You have already requested within 24 hours"}), 429

    request_id = secrets.token_hex(8)
    amount = random_amount()
    c.execute('''INSERT INTO requests (id, username, ip, created_at, amount, status)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (request_id, username, ip, datetime.now(), amount, 'pending'))
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
    c.execute('DELETE FROM requests WHERE id = ?', (request_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    if affected == 0:
        return jsonify({"error": "Request not found"}), 404
    return jsonify({"success": True})

@app.route("/admin/stats", methods=["GET"])
def stats():
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM requests WHERE status = "pending"')
    pending = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM requests')
    total = c.fetchone()[0]
    conn.close()
    return jsonify({"pending": pending, "total": total})

@app.route("/admin/clear", methods=["DELETE"])
def clear_all():
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM requests')
    affected = c.rowcount
    conn.commit()
    conn.close()
    return jsonify({"success": True, "deleted": affected})

# === GIAO DIỆN WEB ===
HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DUCO Faucet Queue</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: linear-gradient(135deg, #1a2a3a 0%, #0f1a24 100%);
            color: #eee;
            margin: 0;
            padding: 2rem;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { font-size: 2.5rem; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.75rem; }
        .badge { background: #2ecc71; padding: 0.2rem 0.8rem; border-radius: 2rem; font-size: 0.9rem; font-weight: normal; }
        .card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border-radius: 1.5rem;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .card h2 { margin-top: 0; color: #f1c40f; }
        .endpoint {
            background: #0f1722;
            border-radius: 1rem;
            padding: 1rem;
            margin: 1rem 0;
            font-family: monospace;
            overflow-x: auto;
        }
        .method {
            display: inline-block;
            background: #2c3e50;
            padding: 0.2rem 0.6rem;
            border-radius: 0.5rem;
            font-weight: bold;
            margin-right: 1rem;
        }
        .method.post { background: #2ecc71; color: #000; }
        .method.get { background: #3498db; }
        .method.delete { background: #e74c3c; }
        .code { background: #00000077; padding: 0.8rem; border-radius: 0.8rem; font-family: monospace; white-space: pre-wrap; }
        .footer { text-align: center; margin-top: 3rem; font-size: 0.8rem; color: #aaa; }
        button {
            background: #f1c40f;
            border: none;
            color: #000;
            padding: 0.5rem 1.2rem;
            border-radius: 2rem;
            font-weight: bold;
            cursor: pointer;
            transition: 0.2s;
        }
        button:hover { background: #e67e22; color: white; }
        input, textarea {
            background: #1f2a3a;
            border: 1px solid #3a4a5a;
            color: white;
            padding: 0.5rem;
            border-radius: 0.5rem;
            width: 100%;
            font-family: monospace;
        }
        .flex { display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; }
        .result { margin-top: 1rem; background: #00000055; padding: 1rem; border-radius: 0.8rem; }
        hr { border-color: #3a4a5a; }
        .amount-badge {
            background: #f1c40f;
            color: #000;
            padding: 0.2rem 0.5rem;
            border-radius: 1rem;
            font-size: 0.8rem;
            font-weight: bold;
            margin-left: 0.5rem;
        }
    </style>
</head>
<body>
<div class="container">
    <h1>🍌 DUCO Faucet Queue <span class="badge">v2.0 + Random Amount</span></h1>
    <p>Server lưu danh sách yêu cầu faucet — mỗi yêu cầu được random từ 0.1 đến 20 DUCO.</p>

    <div class="card">
        <h2>📥 Gửi yêu cầu nhận DUCO (random amount)</h2>
        <div class="flex">
            <input type="text" id="username" placeholder="Username Duino-Coin" style="flex:2">
            <button id="sendReqBtn">Gửi yêu cầu</button>
        </div>
        <div id="sendResult" class="result"></div>
    </div>

    <div class="card">
        <h2>🔧 API dành cho Admin (iPhone)</h2>
        <div class="endpoint">
            <span class="method get">GET</span> <code>/admin/requests</code> – Xem danh sách yêu cầu pending (kèm amount)
        </div>
        <div class="endpoint">
            <span class="method delete">DELETE</span> <code>/admin/requests/{id}</code> – Xóa yêu cầu sau khi gửi coin
        </div>
        <div class="endpoint">
            <span class="method get">GET</span> <code>/admin/stats</code> – Thống kê (pending, total)
        </div>
        <div class="endpoint">
            <span class="method delete">DELETE</span> <code>/admin/clear</code> – Xóa tất cả yêu cầu (cẩn thận)
        </div>
        <details>
            <summary style="cursor:pointer;">📱 Hướng dẫn dùng với iPhone Shortcuts</summary>
            <div class="code">
            <strong>Lấy danh sách:</strong><br>
            URL: <code>{{ request.url_root }}admin/requests</code><br>
            Method: GET<br>
            Headers: X-API-Key: [your_admin_key]<br><br>
            <strong>Xóa yêu cầu:</strong><br>
            URL: <code>{{ request.url_root }}admin/requests/{id}</code><br>
            Method: DELETE<br>
            Headers: X-API-Key: [your_admin_key]
            </div>
        </details>
    </div>

    <div class="card">
        <h2>📊 Thử nghiệm nhanh (Admin)</h2>
        <div class="flex">
            <input type="password" id="adminKey" placeholder="Admin API Key" style="flex:2">
            <button id="fetchStats">Xem thống kê</button>
            <button id="fetchRequests">Xem danh sách</button>
            <button id="clearAll" style="background:#e74c3c;">Xóa tất cả</button>
        </div>
        <div id="adminResult" class="result"></div>
    </div>

    <div class="footer">
        Powered by Flask + SQLite | Deploy trên Render | Mỗi request random amount từ 0.1–20 DUCO
    </div>
</div>

<script>
    const baseUrl = window.location.origin;

    document.getElementById('sendReqBtn').addEventListener('click', async () => {
        const username = document.getElementById('username').value.trim();
        if (!username) return alert('Nhập username');
        const res = await fetch(`${baseUrl}/request`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username})
        });
        const data = await res.json();
        document.getElementById('sendResult').innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    });

    const getAdminKey = () => document.getElementById('adminKey').value.trim();

    async function adminFetch(endpoint, method = 'GET', body = null) {
        const key = getAdminKey();
        if (!key) return alert('Nhập Admin API Key');
        const options = { method, headers: {'X-API-Key': key} };
        if (body) options.body = JSON.stringify(body);
        const res = await fetch(`${baseUrl}${endpoint}`, options);
        const text = await res.text();
        try { return JSON.parse(text); } catch(e) { return text; }
    }

    document.getElementById('fetchStats').addEventListener('click', async () => {
        const data = await adminFetch('/admin/stats');
        document.getElementById('adminResult').innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    });

    document.getElementById('fetchRequests').addEventListener('click', async () => {
        const data = await adminFetch('/admin/requests');
        if (Array.isArray(data)) {
            let html = '<table style="width:100%; border-collapse:collapse;"><tr><th>ID</th><th>Username</th><th>Amount</th><th>IP</th><th>Time</th></tr>';
            data.forEach(r => {
                html += `<tr><td>${r.id}</td><td>${r.username}</td><td class="amount-badge">${r.amount} DUCO</td><td>${r.ip}</td><td>${new Date(r.created_at).toLocaleString()}</td></tr>`;
            });
            html += '</table>';
            document.getElementById('adminResult').innerHTML = html;
        } else {
            document.getElementById('adminResult').innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
        }
    });

    document.getElementById('clearAll').addEventListener('click', async () => {
        if (!confirm('⚠️ Xóa tất cả yêu cầu pending? Hành động này không thể hoàn tác.')) return;
        const data = await adminFetch('/admin/clear', 'DELETE');
        document.getElementById('adminResult').innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    });
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

# === CORS HỖ TRỢ ===
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
