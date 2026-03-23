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
                  received_at TIMESTAMP,
                  ip TEXT)''')
    conn.commit()
    conn.close()

init_db()

# === TẠO FILE ADS.TXT NẾU CHƯA CÓ ===
def create_ads_txt():
    ads_content = """# Google AdSense
google.com, pub-XXXXXXXXXXXXXXXX, DIRECT, f08c47fec0942fa0
"""
    if not os.path.exists('ads.txt'):
        with open('ads.txt', 'w', encoding='utf-8') as f:
            f.write(ads_content)
            print("✅ Đã tạo file ads.txt")

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

def add_to_history(username, amount, ip):
    conn = get_history_db()
    c = conn.cursor()
    c.execute('''INSERT INTO history (username, amount, received_at, ip)
                 VALUES (?, ?, ?, ?)''',
              (username, amount, datetime.now(), ip))
    conn.commit()
    conn.close()

# === ROUTE CHO ADS.TXT ===
@app.route("/ads.txt")
def serve_ads_txt():
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
        return jsonify({"error": "Bạn đã gửi yêu cầu trong 24 giờ qua"}), 429

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
        add_to_history(username, amount, ip)
    
    c.execute('DELETE FROM requests WHERE id = ?', (request_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected == 0:
        return jsonify({"error": "Request not found"}), 404
    return jsonify({"success": True})

# === GIAO DIỆN WEB (RESPONSIVE - ĐÃ BỎ TXID) ===
HTML = """
<!DOCTYPE html>
<html lang="vi">
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
        
        /* Header */
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
        
        .sub {
            color: #94a3b8;
            margin-top: 8px;
            font-size: 0.85rem;
        }
        
        /* Card */
        .card {
            background: rgba(15, 25, 35, 0.7);
            backdrop-filter: blur(12px);
            border-radius: 28px;
            padding: 20px;
            margin-bottom: 24px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            transition: transform 0.2s;
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
        
        /* Form */
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
        
        /* Bảng lịch sử - Responsive */
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
            font-size: 0.7rem;
            color: #9ca3af;
            white-space: nowrap;
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
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>💰 DUCO Faucet <span class="badge">Random 0.1–20</span></h1>
        <div class="sub">Mỗi ngày nhận DUCO miễn phí · Số lượng ngẫu nhiên</div>
    </div>

    <div class="card">
        <h2>📥 Nhận DUCO</h2>
        <div class="form-group">
            <input type="text" id="username" placeholder="Username Duino-Coin (VD: Nam2010)" autocomplete="off">
            <button id="sendReqBtn">🎁 Nhận ngay</button>
        </div>
        <div id="sendResult" class="result"></div>
    </div>

    <div class="card">
        <h2>📜 Lịch sử nhận DUCO</h2>
        <div id="historyContent" class="loading">⏳ Đang tải...</div>
    </div>

    <div class="footer">
        ⚡ 1 lần/ngày · Random 0.1 → 20 DUCO · Giao dịch được ghi nhận ngay sau khi duyệt
    </div>
</div>

<script>
    const baseUrl = window.location.origin;

    const sendBtn = document.getElementById('sendReqBtn');
    const usernameInput = document.getElementById('username');
    const sendResult = document.getElementById('sendResult');
    const historyDiv = document.getElementById('historyContent');

    async function sendRequest() {
        const username = usernameInput.value.trim();
        if (!username) {
            alert('Vui lòng nhập username Duino-Coin');
            return;
        }

        sendBtn.disabled = true;
        sendBtn.textContent = '⏳ Đang xử lý...';
        sendResult.innerHTML = '<span style="color:#fbbf24;">⏳ Đang gửi yêu cầu...</span>';

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
                    <span class="success">✅ Yêu cầu thành công!</span><br>
                    🎲 Số lượng: <strong class="amount-badge">${data.amount} DUCO</strong><br>
                    🆔 Mã: <code>${data.request_id}</code><br>
                    ⏳ Đang chờ duyệt, sẽ nhận trong vài phút
                `;
                usernameInput.value = '';
                loadHistory();
            } else {
                sendResult.innerHTML = `<span class="error">❌ ${data.error || 'Có lỗi xảy ra'}</span>`;
            }
        } catch (err) {
            sendResult.innerHTML = `<span class="error">❌ Lỗi kết nối: ${err.message}</span>`;
        } finally {
            sendBtn.disabled = false;
            sendBtn.textContent = '🎁 Nhận ngay';
        }
    }

    async function loadHistory() {
        try {
            const res = await fetch(`${baseUrl}/history`);
            const data = await res.json();

            if (data.success && data.history.length) {
                let html = `<div class="history-wrapper"><table class="history-table">
                    <thead>
                        <tr><th>Username</th><th>Số lượng</th><th>Thời gian nhận</th></tr>
                    </thead><tbody>`;
                data.history.forEach(item => {
                    const timeStr = new Date(item.received_at).toLocaleString('vi-VN');
                    html += `
                        <tr>
                            <td><strong>${escapeHtml(item.username)}</strong></td>
                            <td><span class="amount-badge">${item.amount} DUCO</span></td>
                            <td class="time-cell">${timeStr}</td>
                        </tr>
                    `;
                });
                html += `</tbody></table></div>`;
                historyDiv.innerHTML = html;
            } else {
                historyDiv.innerHTML = '<p style="text-align:center; color:#6b7280;">📭 Chưa có lịch sử nhận DUCO.</p>';
            }
        } catch (e) {
            historyDiv.innerHTML = '<p class="error">❌ Không tải được lịch sử</p>';
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
    
    history = [{"username": r[0], "amount": r[1], "received_at": r[2]} for r in rows]
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
