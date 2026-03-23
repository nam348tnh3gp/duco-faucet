from flask import Flask, request, jsonify, render_template_string, send_from_directory
import sqlite3
import secrets
import random
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# === CẤU HÌNH ===
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "default-key-change-me")
RATE_LIMIT_HOURS = 24
DB_FILE = 'requests.db'
HISTORY_DB_FILE = 'history.db'
MIN_AMOUNT = 0.1
MAX_AMOUNT = 20.0
STEP = 0.1

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
    
    conn = sqlite3.connect(HISTORY_DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  amount REAL,
                  txid TEXT,
                  received_at TIMESTAMP,
                  ip TEXT)''')
    conn.commit()
    conn.close()

init_db()

# === TẠO FILE ADS.TXT NẾU CHƯA CÓ ===
def create_ads_txt():
    ads_content = """# Google AdSense
google.com, pub-XXXXXXXXXXXXXXXX, DIRECT, f08c47fec0942fa0

# Có thể thêm các dòng khác tùy nhu cầu
# Định dạng: domain, publisher-id, relationship, [certificate-authority-id]
"""
    if not os.path.exists('ads.txt'):
        with open('ads.txt', 'w', encoding='utf-8') as f:
            f.write(ads_content)
            print("✅ Đã tạo file ads.txt")
    else:
        print("📁 File ads.txt đã tồn tại")

create_ads_txt()

# === HELPER ===
def get_db():
    return sqlite3.connect(DB_FILE)

def get_history_db():
    return sqlite3.connect(HISTORY_DB_FILE)

def random_amount():
    steps = int((MAX_AMOUNT - MIN_AMOUNT) / STEP)
    rand_step = random.randint(0, steps)
    return round(MIN_AMOUNT + rand_step * STEP, 1)

def add_to_history(username, amount, txid, ip):
    conn = get_history_db()
    c = conn.cursor()
    c.execute('''INSERT INTO history (username, amount, txid, received_at, ip)
                 VALUES (?, ?, ?, ?, ?)''',
              (username, amount, txid, datetime.now(), ip))
    conn.commit()
    conn.close()

# === ROUTE CHO ADS.TXT ===
@app.route("/ads.txt")
def serve_ads_txt():
    """Phục vụ file ads.txt cho Google AdSense"""
    return send_from_directory('.', 'ads.txt', mimetype='text/plain')

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
    c.execute('SELECT username, amount, ip FROM requests WHERE id = ?', (request_id,))
    row = c.fetchone()
    
    if row:
        username, amount, ip = row
        add_to_history(username, amount, "pending", ip)
    
    c.execute('DELETE FROM requests WHERE id = ?', (request_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected == 0:
        return jsonify({"error": "Request not found"}), 404
    return jsonify({"success": True})

@app.route("/admin/update_txid", methods=["POST"])
def update_txid():
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    username = data.get("username")
    txid = data.get("txid")
    
    if not username or not txid:
        return jsonify({"error": "Missing username or txid"}), 400
    
    conn = get_history_db()
    c = conn.cursor()
    c.execute('''UPDATE history 
                 SET txid = ? 
                 WHERE username = ? AND txid = 'pending' 
                 ORDER BY received_at DESC LIMIT 1''', 
              (txid, username))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected > 0:
        return jsonify({"success": True})
    return jsonify({"success": False})

# === GIAO DIỆN WEB ===
HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DUCO Faucet</title>
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
        .container { max-width: 1000px; margin: 0 auto; }
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
        .flex { display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; }
        button {
            background: #f1c40f;
            border: none;
            color: #000;
            padding: 0.6rem 1.5rem;
            border-radius: 2rem;
            font-weight: bold;
            cursor: pointer;
            transition: 0.2s;
            font-size: 1rem;
        }
        button:hover { background: #e67e22; color: white; transform: scale(1.02); }
        input {
            background: #1f2a3a;
            border: 1px solid #3a4a5a;
            color: white;
            padding: 0.6rem 1rem;
            border-radius: 2rem;
            width: 100%;
            font-family: monospace;
            font-size: 1rem;
        }
        .result { 
            margin-top: 1rem; 
            background: #00000055; 
            padding: 1rem; 
            border-radius: 1rem;
            font-family: monospace;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .history-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        .history-table th, .history-table td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .history-table th {
            background: rgba(241, 196, 15, 0.2);
            color: #f1c40f;
        }
        .amount-badge {
            background: #f1c40f;
            color: #000;
            padding: 0.2rem 0.6rem;
            border-radius: 1rem;
            font-size: 0.8rem;
            font-weight: bold;
            display: inline-block;
        }
        .footer { text-align: center; margin-top: 3rem; font-size: 0.8rem; color: #aaa; }
        .success { color: #2ecc71; }
        .error { color: #e74c3c; }
        .loading { text-align: center; padding: 2rem; color: #aaa; }
        code { background: #00000044; padding: 0.2rem 0.4rem; border-radius: 0.3rem; font-size: 0.85rem; }
    </style>
</head>
<body>
<div class="container">
    <h1>🍌 DUCO Faucet <span class="badge">Random 0.1 - 20 DUCO</span></h1>
    <p>Nhận DUCO miễn phí mỗi ngày một lần — số lượng ngẫu nhiên</p>

    <div class="card">
        <h2>📥 Gửi yêu cầu nhận DUCO</h2>
        <div class="flex">
            <input type="text" id="username" placeholder="Username Duino-Coin (ví dụ: Nam2010)" style="flex:2">
            <button id="sendReqBtn">🎁 Nhận DUCO</button>
        </div>
        <div id="sendResult" class="result"></div>
    </div>

    <div class="card">
        <h2>📜 Lịch sử nhận DUCO (50 gần nhất)</h2>
        <div id="historyContent" class="loading">⏳ Đang tải lịch sử...</div>
    </div>

    <div class="footer">
        ⚡ Mỗi username chỉ được nhận 1 lần/ngày | Số lượng random từ 0.1 đến 20 DUCO
    </div>
</div>

<script>
    const baseUrl = window.location.origin;

    document.getElementById('sendReqBtn').addEventListener('click', async () => {
        const username = document.getElementById('username').value.trim();
        if (!username) {
            alert('Vui lòng nhập username Duino-Coin');
            return;
        }
        
        const btn = document.getElementById('sendReqBtn');
        const resultDiv = document.getElementById('sendResult');
        
        btn.disabled = true;
        btn.textContent = '⏳ Đang xử lý...';
        resultDiv.innerHTML = '<span style="color:#f1c40f;">⏳ Đang gửi yêu cầu...</span>';
        
        try {
            const res = await fetch(`${baseUrl}/request`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username})
            });
            const data = await res.json();
            
            if (res.status === 429) {
                resultDiv.innerHTML = `<span class="error">❌ ${data.error}</span>`;
            } else if (data.success) {
                resultDiv.innerHTML = `
                    <span class="success">✅ Yêu cầu thành công!</span><br>
                    🎲 Số lượng: <strong class="amount-badge">${data.amount} DUCO</strong><br>
                    🆔 Mã yêu cầu: <code>${data.request_id}</code><br>
                    ⏳ Vui lòng chờ admin xử lý (có thể mất vài phút)
                `;
                document.getElementById('username').value = '';
                loadHistory();
            } else {
                resultDiv.innerHTML = `<span class="error">❌ ${data.error || 'Có lỗi xảy ra'}</span>`;
            }
        } catch (error) {
            resultDiv.innerHTML = `<span class="error">❌ Lỗi kết nối: ${error.message}</span>`;
        } finally {
            btn.disabled = false;
            btn.textContent = '🎁 Nhận DUCO';
        }
    });

    async function loadHistory() {
        const historyDiv = document.getElementById('historyContent');
        try {
            const res = await fetch(`${baseUrl}/history`);
            const data = await res.json();
            
            if (data.success && data.history.length > 0) {
                let html = '<table class="history-table">';
                html += '<thead><tr><th>Username</th><th>Số lượng</th><th>TxID</th><th>Thời gian nhận</th></tr></thead><tbody>';
                data.history.forEach(item => {
                    const txidDisplay = item.txid && item.txid !== 'pending' ? 
                        `<code style="font-size:0.75rem">${item.txid.substring(0, 16)}...</code>` : 
                        '<span style="color:#f1c40f;">⏳ Đang xử lý</span>';
                    html += `
                        <tr>
                            <td><strong>${escapeHtml(item.username)}</strong></td>
                            <td><span class="amount-badge">${item.amount} DUCO</span></td>
                            <td>${txidDisplay}</td>
                            <td>${new Date(item.received_at).toLocaleString('vi-VN')}</td>
                        </tr>
                    `;
                });
                html += '</tbody></table>';
                historyDiv.innerHTML = html;
            } else {
                historyDiv.innerHTML = '<p style="text-align:center; color:#aaa;">📭 Chưa có lịch sử nhận DUCO. Hãy là người đầu tiên!</p>';
            }
        } catch(e) {
            console.error(e);
            historyDiv.innerHTML = '<p class="error">❌ Không thể tải lịch sử</p>';
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

    loadHistory();
    setInterval(loadHistory, 30000);
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
    c.execute('SELECT username, amount, txid, received_at FROM history ORDER BY received_at DESC LIMIT 50')
    rows = c.fetchall()
    conn.close()
    
    history = []
    for row in rows:
        history.append({
            "username": row[0],
            "amount": row[1],
            "txid": row[2] if row[2] else "pending",
            "received_at": row[3]
        })
    
    return jsonify({"success": True, "history": history})

# === CORS HỖ TRỢ ===
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
