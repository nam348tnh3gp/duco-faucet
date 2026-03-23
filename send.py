import os
import time
import requests
import json
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlencode
from dotenv import load_dotenv

# Load biến từ file .env
load_dotenv()

# ===== CẤU HÌNH ĐỌC TỪ .ENV =====
RENDER_API_URL = os.getenv("RENDER_API_URL")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
FAUCET_USERNAME = os.getenv("FAUCET_USERNAME")
FAUCET_PASSWORD = os.getenv("FAUCET_PASSWORD")
MEMO = os.getenv("MEMO", "Faucet")
USE_REQUEST_AMOUNT = os.getenv("USE_REQUEST_AMOUNT", "true").lower() == "true"
FALLBACK_AMOUNT = float(os.getenv("FALLBACK_AMOUNT", "0.1"))
SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", "30"))

# Kiểm tra các biến bắt buộc
if not RENDER_API_URL:
    print("❌ Lỗi: Thiếu RENDER_API_URL trong file .env")
    exit(1)
if not ADMIN_API_KEY:
    print("❌ Lỗi: Thiếu ADMIN_API_KEY trong file .env")
    exit(1)
if not FAUCET_USERNAME:
    print("❌ Lỗi: Thiếu FAUCET_USERNAME trong file .env")
    exit(1)
if not FAUCET_PASSWORD:
    print("❌ Lỗi: Thiếu FAUCET_PASSWORD trong file .env")
    exit(1)

# ===== KHỞI TẠO DATABASE LOCAL ĐỂ LƯU LỊCH SỬ GỬI COIN =====
DB_FILE = 'sent_history.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sent_history
                 (username TEXT PRIMARY KEY,
                  last_sent TIMESTAMP,
                  amount REAL,
                  txid TEXT)''')
    conn.commit()
    conn.close()

init_db()

def check_user_eligibility(username):
    """Kiểm tra xem username đã nhận coin trong 24h qua chưa"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT last_sent FROM sent_history WHERE username = ?', (username,))
    row = c.fetchone()
    conn.close()
    
    if row:
        last_sent = datetime.fromisoformat(row[0])
        time_diff = datetime.now() - last_sent
        if time_diff < timedelta(hours=24):
            return False, f"Đã nhận coin lúc {last_sent.strftime('%H:%M %d/%m/%Y')}, còn {24 - time_diff.seconds//3600} giờ {((24*3600 - time_diff.seconds)//60)%60} phút nữa mới được nhận tiếp"
    return True, None

def record_sent(username, amount, txid):
    """Ghi nhận đã gửi coin cho username"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO sent_history (username, last_sent, amount, txid)
                 VALUES (?, ?, ?, ?)''',
              (username, datetime.now().isoformat(), amount, txid))
    conn.commit()
    conn.close()

# ===== HÀM GỬI COIN QUA DUCO SERVER =====
def send_duco(recipient, amount):
    # Kiểm tra username đã nhận trong 24h chưa
    eligible, msg = check_user_eligibility(recipient)
    if not eligible:
        return False, msg
    
    params = {
        "username": FAUCET_USERNAME,
        "password": FAUCET_PASSWORD,
        "recipient": recipient,
        "amount": amount,
        "memo": MEMO
    }
    url = f"https://server.duinocoin.com/transaction/?{urlencode(params)}"
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 405:
            return False, "Method Not Allowed - Server DUCO yêu cầu POST, đang thử phương thức khác"
        
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
        
        # Parse JSON
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return False, f"Lỗi parse JSON. Response: {response.text[:200]}"
        
        if data.get("success"):
            # Ghi nhận đã gửi thành công
            record_sent(recipient, amount, data.get("txid", "unknown"))
            return True, data.get("txid", "unknown")
        else:
            return False, data.get("message", "Unknown error")
            
    except requests.exceptions.Timeout:
        return False, "Timeout - Server DUCO không phản hồi"
    except requests.exceptions.ConnectionError:
        return False, "Connection Error - Không thể kết nối đến server DUCO"
    except Exception as e:
        return False, f"Lỗi: {str(e)}"

# ===== LẤY DANH SÁCH YÊU CẦU TỪ RENDER =====
def get_pending_requests():
    headers = {"X-API-Key": ADMIN_API_KEY}
    try:
        resp = requests.get(f"{RENDER_API_URL}/admin/requests", headers=headers, timeout=15)
        if resp.status_code == 404:
            print("❌ Endpoint /admin/requests không tồn tại. Kiểm tra lại URL Render hoặc deploy lại server.")
            return []
        if resp.status_code != 200:
            print(f"❌ Không thể lấy danh sách yêu cầu: HTTP {resp.status_code}")
            return []
        
        try:
            return resp.json()
        except json.JSONDecodeError:
            print(f"❌ Server trả về không phải JSON")
            return []
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi kết nối đến Render: {e}")
        return []

# ===== XÓA YÊU CẦU SAU KHI XỬ LÝ =====
def delete_request(request_id):
    headers = {"X-API-Key": ADMIN_API_KEY}
    try:
        resp = requests.delete(f"{RENDER_API_URL}/admin/requests/{request_id}", headers=headers, timeout=10)
        if resp.status_code == 404:
            return True
        return resp.status_code == 200
    except:
        return False

# ===== XỬ LÝ MỘT LƯỢT =====
def process_batch():
    print("\n" + "="*50)
    print("🍌 Đang lấy danh sách yêu cầu faucet...")
    requests_list = get_pending_requests()
    
    if not requests_list:
        print("✅ Không có yêu cầu nào cần xử lý.")
        return

    print(f"📋 Tìm thấy {len(requests_list)} yêu cầu.")
    
    for req in requests_list:
        rid = req.get("id")
        username = req.get("username")
        
        if not rid or not username:
            print(f"⚠️ Yêu cầu thiếu thông tin: {req}")
            continue
            
        if USE_REQUEST_AMOUNT and "amount" in req:
            amount = req["amount"]
        else:
            amount = FALLBACK_AMOUNT
            
        print(f"\n🔹 Xử lý yêu cầu từ {username} (ID: {rid})")
        print(f"   💰 Số lượng: {amount} DUCO")
        
        # Kiểm tra eligibility trước khi gửi
        eligible, msg = check_user_eligibility(username)
        if not eligible:
            print(f"   ⏰ {msg}")
            print(f"   🗑 Xóa yêu cầu khỏi queue (không hợp lệ)")
            if delete_request(rid):
                print("   🗑 Đã xóa yêu cầu khỏi queue.")
            continue
        
        success, info = send_duco(username, amount)
        
        if success:
            print(f"   ✅ Đã gửi {amount} DUCO đến {username}")
            print(f"   🔗 TxID: {info}")
            
            if delete_request(rid):
                print("   🗑 Đã xóa yêu cầu khỏi queue.")
            else:
                print("   ⚠️ Gửi thành công nhưng không xóa được yêu cầu")
        else:
            print(f"   ❌ Gửi thất bại: {info}")
            # Không xóa yêu cầu để xử lý lại sau

# ===== XEM LỊCH SỬ ĐÃ GỬI =====
def show_history():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT username, last_sent, amount, txid FROM sent_history ORDER BY last_sent DESC LIMIT 20')
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        print("📭 Chưa có lịch sử gửi coin.")
        return
    
    print("\n📜 Lịch sử 20 giao dịch gần nhất:")
    print("-" * 80)
    for username, last_sent, amount, txid in rows:
        sent_time = datetime.fromisoformat(last_sent)
        print(f"👤 {username} | {amount} DUCO | {sent_time.strftime('%d/%m/%Y %H:%M:%S')} | TxID: {txid[:16]}...")

# ===== VÒNG LẶP AUTO =====
def main_auto():
    print("🚀 Auto Faucet Processor Started")
    print(f"📍 Render API: {RENDER_API_URL}")
    print(f"👤 Faucet Username: {FAUCET_USERNAME}")
    print(f"⏱️  Kiểm tra mỗi {SLEEP_INTERVAL} giây")
    print("="*50)
    
    while True:
        try:
            process_batch()
        except KeyboardInterrupt:
            print("\n\n🛑 Đã dừng bởi người dùng.")
            show_history()
            break
        except Exception as e:
            print(f"⚠️ Lỗi không xác định: {e}")
        
        print(f"\n⏳ Chờ {SLEEP_INTERVAL} giây...")
        time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    main_auto()
