import requests
import time
from typing import Dict, List, Optional
import os

# ---------------- CONFIG ----------------
TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

_cached_token = None
_token_expiry = 0  # UNIX timestamp


# ---------------- ACCESS TOKEN ----------------
def get_access_token() -> str:
    global _cached_token, _token_expiry

    # Хэрвээ token хүчинтэй байвал cache-аас буцаана
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


# ---------------- USER SEARCH CLASS ----------------
class MicrosoftUsersAPI:
    def __init__(self, access_token: str):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    def search_users_by_job_title(self, job_title: str) -> List[Dict]:
        """Албан тушаалаар хэрэглэгч хайх"""
        # URL encode хийх (зай болон тусгай тэмдэгтүүдийг зөв кодлох)
        from urllib.parse import quote
        encoded_job_title = quote(job_title)
        
        url = f"{self.base_url}/users?$select=id,displayName,mail,jobTitle,department,accountEnabled&$filter=jobTitle eq '{encoded_job_title}'"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            print(f"❌ Хэрэглэгч хайхад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return []
        
        return response.json().get("value", [])

    def search_users_by_partial_job_title(self, partial_title: str) -> List[Dict]:
        """Албан тушаалын хэсэгчилсэн нэрээр хайх (contains)"""
        from urllib.parse import quote
        encoded_title = quote(partial_title)
        
        url = f"{self.base_url}/users?$select=id,displayName,mail,jobTitle,department,accountEnabled&$filter=contains(jobTitle, '{encoded_title}')"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            print(f"❌ Хэрэглэгч хайхад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return []
        
        return response.json().get("value", [])

    def get_all_users_with_job_titles(self) -> List[Dict]:
        """Албан тушаалтай бүх хэрэглэгчдийг авах"""
        url = f"{self.base_url}/users?$select=id,displayName,mail,jobTitle,department,accountEnabled&$filter=jobTitle ne null"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            print(f"❌ Хэрэглэгчдийг авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return []
        
        return response.json().get("value", [])

    def print_users_info(self, users: List[Dict], search_term: str = ""):
        """Хэрэглэгчдийн мэдээллийг хэвлэх (зөвхөн идэвхтэй account)"""
        if not users:
            print(f"❌ '{search_term}' албан тушаалтай хэрэглэгч олдсонгүй")
            return
        
        # Зөвхөн accountEnabled = true байгаа хэрэглэгчдийг шүүх
        active_users = [user for user in users if user.get('accountEnabled', True)]
        
        if not active_users:
            print(f"❌ '{search_term}' албан тушаалтай идэвхтэй хэрэглэгч олдсонгүй")
            return
        
        print(f"✅ '{search_term}' хайлтаар {len(active_users)} идэвхтэй хэрэглэгч олдлоо:")
        print("-" * 80)
        
        for i, user in enumerate(active_users, 1):
            account_enabled = user.get('accountEnabled', True)
            print(f"{i}. {user.get('displayName', 'Нэргүй')}")
            print(f"   И-мэйл: {user.get('mail', 'N/A')}")
            print(f"   Албан тушаал: {user.get('jobTitle', 'N/A')}")
            print(f"   Хэлтэс: {user.get('Department', 'N/A')}")
            print(f"   ID: {user.get('id', 'N/A')}")
            print(f"   Account enabled: {'✅ Yes' if account_enabled else '❌ No'}")
            print("-" * 40)


# ---------------- MAIN ----------------
def main():
    token = get_access_token()
    users_api = MicrosoftUsersAPI(token)
    
    # Сонголт 1: Тодорхой албан тушаалаар хайх
    job_title = "Chief Executive Officer"
    print(f"🔍 '{job_title}' албан тушаалтай хэрэглэгчдийг хайж байна...")
    exact_users = users_api.search_users_by_job_title(job_title)
    users_api.print_users_info(exact_users, job_title)
    
    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
