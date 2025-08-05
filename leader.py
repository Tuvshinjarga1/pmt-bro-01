import requests
import time
import os
from typing import Dict, List, Optional

# Environment variables-аас унших
CLIENT_ID = os.getenv("CLIENT_ID", "a6e958a7-e8df-4e83-a8c2-5dc73f93bdc4")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID", "3fee1c11-7cdf-44b4-a1b0-5183408e1d89")

# ---------------- GLOBAL VARIABLES ----------------
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

    def search_user_by_email(self, email: str) -> Optional[Dict]:
        """И-мэйлээр хэрэглэгч хайх"""
        url = f"{self.base_url}/users"
        params = {
            "$filter": f"mail eq '{email}'",
            "$select": "id,displayName,mail,jobTitle,department,accountEnabled"
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        
        if response.status_code != 200:
            print(f"❌ Хэрэглэгч хайхад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return None
        
        users = response.json().get("value", [])
        return users[0] if users else None

    def get_user_manager(self, user_id: str) -> Optional[Dict]:
        """Хэрэглэгчийн manager-ийг олох"""
        url = f"{self.base_url}/users/{user_id}/manager"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 404:
            print("ℹ️ Энэ хэрэглэгчид manager тохируулагдаагүй байна")
            return None
        elif response.status_code != 200:
            print(f"❌ Manager хайхад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return None
        
        return response.json()

    def print_user_info(self, user: Dict, title: str = "Хэрэглэгчийн мэдээлэл"):
        """Нэг хэрэглэгчийн мэдээллийг хэвлэх"""
        print(f"\n{title}:")
        print("-" * 50)
        print(f"Нэр: {user.get('displayName', 'N/A')}")
        print(f"И-мэйл: {user.get('mail', 'N/A')}")
        print(f"Албан тушаал: {user.get('jobTitle', 'N/A')}")
        print(f"Хэлтэс: {user.get('department', 'N/A')}")
        print(f"ID: {user.get('id', 'N/A')}")
        print(f"Account enabled: {'✅ Yes' if user.get('accountEnabled', True) else '❌ No'}")

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


# ---------------- MANAGER LOOKUP FUNCTIONS FOR APP.PY ----------------
def get_user_manager_id(user_email: str) -> Optional[str]:
    """Хэрэглэгчийн manager-ийн ID-г авах (app.py-д ашиглах)"""
    try:
        token = get_access_token()
        users_api = MicrosoftUsersAPI(token)
        
        # Хэрэглэгчийг олох
        user = users_api.search_user_by_email(user_email)
        if not user:
            print(f"❌ Хэрэглэгч олдсонгүй: {user_email}")
            return None
        
        # Manager-ийг олох
        manager = users_api.get_user_manager(user.get('id'))
        if not manager:
            print(f"❌ Manager олдсонгүй: {user_email}")
            return None
        
        return manager.get('id')
        
    except Exception as e:
        print(f"❌ Manager хайхад алдаа гарлаа: {str(e)}")
        return None

def get_user_manager_info(user_email: str) -> Optional[Dict]:
    """Хэрэглэгчийн manager-ийн бүх мэдээллийг авах (app.py-д ашиглах)"""
    try:
        token = get_access_token()
        users_api = MicrosoftUsersAPI(token)
        
        # Хэрэглэгчийг олох
        user = users_api.search_user_by_email(user_email)
        if not user:
            print(f"❌ Хэрэглэгч олдсонгүй: {user_email}")
            return None
        
        # Manager-ийг олох
        manager = users_api.get_user_manager(user.get('id'))
        if not manager:
            print(f"❌ Manager олдсонгүй: {user_email}")
            return None
        
        return manager
        
    except Exception as e:
        print(f"❌ Manager хайхад алдаа гарлаа: {str(e)}")
        return None


# ---------------- MAIN ----------------
def main():
    token = get_access_token()
    users_api = MicrosoftUsersAPI(token)
    
    print("🔍 Хэрэглэгчийн manager хайх систем")
    print("=" * 50)
    
    # Хэрэглэгчийн и-мэйл эсвэл нэр оруулах
    user_input = input("Хэрэглэгчийн и-мэйл оруулна уу: ").strip()
    
    if not user_input:
        print("❌ Хэрэглэгчийн мэдээлэл оруулаагүй байна")
        return
    
    # И-мэйл эсвэл нэрээр хайх
    user = None
    if '@' in user_input:
        # И-мэйл байна
        user = users_api.search_user_by_email(user_input)
    
    if not user:
        print(f"❌ '{user_input}' хэрэглэгч олдсонгүй")
        return
    
    # Хэрэглэгчийн мэдээллийг харуулах
    users_api.print_user_info(user, "Олдсон хэрэглэгч")
    
    # Manager хайх
    print(f"\n🔍 {user.get('displayName')}-ийн manager-ийг хайж байна...")
    manager = users_api.get_user_manager(user.get('id'))
    
    if manager:
        users_api.print_user_info(manager, "Manager")
    else:
        print("ℹ️ Энэ хэрэглэгчид manager тохируулагдаагүй байна")
    
if __name__ == "__main__":
    main()