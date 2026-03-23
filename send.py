import os
import time
import requests
import json
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

# === CẤU HÌNH ===
RENDER_API_URL = os.getenv("RENDER_API_URL")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
FAUCET_USERNAME = os.getenv("FAUCET_USERNAME")
FAUCET_PASSWORD = os.getenv("FAUCET_PASSWORD")
MEMO = os.getenv("MEMO", "Faucet")
USE_REQUEST_AMOUNT = os.getenv("USE_REQUEST_AMOUNT", "true").lower() == "true"
FALLBACK_AMOUNT = float(os.getenv("FALLBACK_AMOUNT", "0.1"))
SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", "30"))

# === DATABASE LOCAL ===
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
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT last_sent, amount FROM sent_history WHERE username = ?', (username,))
    row = c.fetchone()
    conn.close()
    
    if row:
        last_sent = datetime.fromisoformat(row[0])
        if datetime.now() - last_sent < timedelta(hours=24):
            return False, f"Already claimed {row[1]} DUCO recently"
    return True, None

def record_sent(username, amount, txid):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO sent_history (username, last_sent, amount, txid)
                 VALUES (?, ?, ?, ?)''',
              (username, datetime.now().isoformat(), amount, txid))
    conn.commit()
    conn.close()

# === GỬI COIN ===
def send_duco(recipient, amount):
    eligible, msg = check_user_eligibility(recipient)
    if not eligible:
        return False, msg, True
    
    params = {
        "username": FAUCET_USERNAME,
        "password": FAUCET_PASSWORD,
        "recipient": recipient,
        "amount": amount,
        "memo": MEMO
    }
    url = f"https://server.duinocoin.com/transaction/?{urlencode(params)}"
    
    try:
        response = requests.get(url, timeout=15)
        text = response.text
        
        # Xử lý HTTP status codes
        if response.status_code == 429:
            return False, "Rate limited (429)", True
        if response.status_code == 403:
            return False, "Blocked (403)", True
        if response.status_code >= 500:
            return False, f"Server error {response.status_code}", False  # Giữ lại, thử sau
        
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}", True
        
        # Parse JSON
        try:
            data = json.loads(text)
        except:
            return False, f"Invalid JSON", True
        
        if data.get("success"):
            record_sent(recipient, amount, data.get("txid", "unknown"))
            return True, data.get("txid"), False
        else:
            msg = data.get("message", "Unknown error")
            msg_lower = msg.lower()
            
            # Lỗi không thể fix → xóa request
            should_delete = any(key in msg_lower for key in [
                "doesn't exist", "recipient doesn't exist", "invalid username",
                "sending funds to yourself", "to yourself", "same account"
            ])
            
            # Lỗi block/rate limit → cần nghỉ lâu
            if "blocked" in msg_lower or "banned" in msg_lower:
                return False, f"Blocked: {msg}", True
            
            return False, msg, should_delete
            
    except requests.exceptions.Timeout:
        return False, "Timeout", False
    except requests.exceptions.ConnectionError:
        return False, "Connection error", False
    except Exception as e:
        return False, str(e), False

# === LẤY DANH SÁCH ===
def get_pending_requests():
    headers = {"X-API-Key": ADMIN_API_KEY}
    try:
        resp = requests.get(f"{RENDER_API_URL}/admin/requests", headers=headers, timeout=15)
        if resp.status_code != 200:
            return []
        return resp.json()
    except:
        return []

# === XÓA YÊU CẦU ===
def delete_request(request_id):
    headers = {"X-API-Key": ADMIN_API_KEY}
    try:
        resp = requests.delete(f"{RENDER_API_URL}/admin/requests/{request_id}", headers=headers, timeout=10)
        return resp.status_code in (200, 404)
    except:
        return False

# === XỬ LÝ ===
def process_batch():
    print("\n" + "="*50)
    print("🍌 Fetching pending requests...")
    requests_list = get_pending_requests()
    
    if not requests_list:
        print("✅ No pending requests")
        return
    
    print(f"📋 Found {len(requests_list)} requests")
    
    # Biến để theo dõi block/rate limit
    is_blocked = False
    block_reason = ""
    
    for req in requests_list:
        # Nếu đang bị block, dừng xử lý các request còn lại
        if is_blocked:
            print(f"\n⛔ Bot is blocked ({block_reason})")
            print(f"   ⏸️  Pausing for 5 minutes before retry...")
            return  # Thoát batch, chờ main loop retry
        
        rid = req.get("id")
        username = req.get("username")
        amount = req.get("amount", FALLBACK_AMOUNT) if USE_REQUEST_AMOUNT else FALLBACK_AMOUNT
        
        if not rid or not username:
            continue
        
        print(f"\n🔹 {username} | {amount} DUCO")
        
        success, info, should_delete = send_duco(username, amount)
        
        if success:
            print(f"   ✅ Sent {amount} DUCO to {username}")
            print(f"   🔗 TxID: {info}")
            delete_request(rid)
        else:
            print(f"   ❌ Failed: {info}")
            
            # Phát hiện block
            if "blocked" in info.lower() or "banned" in info.lower():
                is_blocked = True
                block_reason = info
                print(f"   ⛔ Bot is blocked, will pause")
                # Không xóa request, giữ lại
            elif "rate limited" in info.lower() or "429" in info:
                print(f"   ⏸️  Rate limit, waiting 30s before next request")
                time.sleep(30)
            elif should_delete:
                print(f"   🗑 Deleting invalid request")
                delete_request(rid)
            else:
                print(f"   ⏳ Keeping request for retry")

# === MAIN ===
def main():
    print("🚀 Auto Faucet Processor Started")
    print(f"📍 Render: {RENDER_API_URL}")
    print(f"👤 Faucet: {FAUCET_USERNAME}")
    
    global_blocked = False
    block_backoff = 60  # bắt đầu với 1 phút
    
    while True:
        try:
            if global_blocked:
                print(f"\n⛔ Global block detected, waiting {block_backoff} seconds...")
                time.sleep(block_backoff)
                # Tăng dần thời gian chờ
                block_backoff = min(block_backoff * 2, 600)  # tối đa 10 phút
                global_blocked = False
            
            process_batch()
            # Reset block backoff nếu thành công
            block_backoff = 60
            
        except KeyboardInterrupt:
            print("\n🛑 Stopped")
            break
        except Exception as e:
            print(f"⚠️ Error: {e}")
            if "blocked" in str(e).lower() or "429" in str(e):
                global_blocked = True
        
        print(f"\n⏳ Waiting {SLEEP_INTERVAL}s...")
        time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    main()
