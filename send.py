import os
import requests
from dotenv import load_dotenv

# Load biến từ file .env (nếu có)
load_dotenv()

# ===== CẤU HÌNH TỪ BIẾN MÔI TRƯỜNG =====
RENDER_API_URL = os.getenv("RENDER_API_URL", "https://your-app.onrender.com")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "your_secret_key_here")
FAUCET_USERNAME = os.getenv("FAUCET_USERNAME", "Nam2010")
FAUCET_PASSWORD = os.getenv("FAUCET_PASSWORD", "12345678./")
MEMO = os.getenv("MEMO", "Faucet")
USE_REQUEST_AMOUNT = os.getenv("USE_REQUEST_AMOUNT", "true").lower() == "true"
FALLBACK_AMOUNT = float(os.getenv("FALLBACK_AMOUNT", "0.1"))

# ===== HÀM GỬI COIN QUA DUCO SERVER =====
def send_duco(recipient, amount):
    url = "https://server.duinocoin.com/transaction/"
    payload = {
        "username": FAUCET_USERNAME,
        "password": FAUCET_PASSWORD,
        "recipient": recipient,
        "amount": amount,
        "memo": MEMO
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        if data.get("success"):
            return True, data.get("txid")
        else:
            return False, data.get("message", "Unknown error")
    except Exception as e:
        return False, str(e)

# ===== LẤY DANH SÁCH YÊU CẦU TỪ RENDER =====
def get_pending_requests():
    headers = {"X-API-Key": ADMIN_API_KEY}
    try:
        resp = requests.get(f"{RENDER_API_URL}/admin/requests", headers=headers, timeout=15)
        if resp.status_code != 200:
            print("❌ Không thể lấy danh sách yêu cầu:", resp.text)
            return []
        return resp.json()
    except requests.exceptions.RequestException as e:
        print("❌ Lỗi kết nối:", e)
        return []

# ===== XÓA YÊU CẦU SAU KHI XỬ LÝ =====
def delete_request(request_id):
    headers = {"X-API-Key": ADMIN_API_KEY}
    try:
        resp = requests.delete(f"{RENDER_API_URL}/admin/requests/{request_id}", headers=headers, timeout=10)
        return resp.status_code == 200
    except:
        return False

# ===== XỬ LÝ CHÍNH =====
def main():
    print("🍌 Đang lấy danh sách yêu cầu faucet...")
    requests_list = get_pending_requests()
    if not requests_list:
        print("✅ Không có yêu cầu nào cần xử lý.")
        return

    print(f"📋 Tìm thấy {len(requests_list)} yêu cầu.")
    for req in requests_list:
        rid = req["id"]
        username = req["username"]
        # Quyết định số lượng DUCO sẽ gửi
        if USE_REQUEST_AMOUNT and "amount" in req:
            amount = req["amount"]
        else:
            amount = FALLBACK_AMOUNT
        print(f"\n🔹 Xử lý yêu cầu từ {username} (ID: {rid}) với amount: {amount} DUCO...")
        success, info = send_duco(username, amount)
        if success:
            print(f"   ✅ Đã gửi {amount} DUCO đến {username}. TxID: {info}")
            if delete_request(rid):
                print("   🗑 Đã xóa yêu cầu khỏi queue.")
            else:
                print("   ⚠️ Gửi coin thành công nhưng không xóa được yêu cầu (cần xóa thủ công).")
        else:
            print(f"   ❌ Gửi thất bại: {info}")

if __name__ == "__main__":
    main()
