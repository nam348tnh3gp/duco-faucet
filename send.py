import os
import time
import requests
import json
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

# ===== HÀM GỬI COIN QUA DUCO SERVER (DÙNG GET METHOD) =====
def send_duco(recipient, amount):
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
            break
        except Exception as e:
            print(f"⚠️ Lỗi không xác định: {e}")
        
        print(f"\n⏳ Chờ {SLEEP_INTERVAL} giây...")
        time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    main_auto()
