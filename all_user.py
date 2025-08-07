import requests
import time
from typing import List, Dict
import os
# ---------------- CONFIG ----------------
TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

_cached_token = None
_token_expiry = 0


# ---------------- ACCESS TOKEN ----------------
def get_access_token() -> str:
    global _cached_token, _token_expiry

    if _cached_token and time.time() < _token_expiry - 10:
        return _cached_token

    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    headers = { "Content-Type": "application/x-www-form-urlencoded" }
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }

    response = requests.post(url, headers=headers, data=data)
    if response.status_code != 200:
        print("❌ Access token авахад алдаа гарлаа:")
        print("Status code:", response.status_code)
        print("Response:", response.text)
        raise Exception("Access token авахад амжилтгүй боллоо")

    token_data = response.json()
    _cached_token = token_data["access_token"]
    _token_expiry = time.time() + token_data.get("expires_in", 3600)

    return _cached_token


# ---------------- USERS API ----------------
class MicrosoftUsersAPI:
    def __init__(self, access_token: str):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    def get_all_users(self) -> List[Dict]:
        """Бүх идэвхтэй хэрэглэгчдийг авах (jobTitle байгаа тохиолдолд)"""
        url = f"{self.base_url}/users?$select=id,displayName,mail,userPrincipalName,jobTitle,department,accountEnabled&$top=999"
        users = []

        while url:
            response = requests.get(url, headers=self.headers)
            if response.status_code != 200:
                print("❌ Хэрэглэгчдийг авахад алдаа гарлаа:")
                print("Status code:", response.status_code)
                print("Response:", response.text)
                break

            data = response.json()
            users.extend(data.get("value", []))
            url = data.get("@odata.nextLink")

        # ✅ Зөвхөн идэвхтэй бөгөөд jobTitle-той хэрэглэгчдийг буцаах
        filtered_users = [
            user for user in users
            if user.get("accountEnabled", True) and user.get("jobTitle")
        ]
        return filtered_users


# ---------------- MAIN ----------------
def main():
    print("🔐 Access token авч байна...")
    token = get_access_token()

    print("📥 Идэвхтэй бөгөөд албан тушаалтай хэрэглэгчдийг авч байна...")
    api = MicrosoftUsersAPI(token)
    users = api.get_all_users()

    print(f"\n✅ Нийт идэвхтэй, jobTitle-той хэрэглэгч: {len(users)}")
    print("-" * 80)

    for i, user in enumerate(users, 1):
        name = user.get("displayName", "Нэргүй")
        email = user.get("mail") or user.get("userPrincipalName", "N/A")
        job = user.get("jobTitle")
        dept = user.get("department", "N/A")
        print(f"{i}. {name}")
        print(f"   📧 {email}")
        print(f"   📌 {job}")
        print(f"   🏢 {dept}")
        print("-" * 40)


# Export functions for external use
__all__ = ["get_access_token", "MicrosoftUsersAPI"]

if __name__ == "__main__":
    main()
