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


# ---------------- PLANNER TASKS CLASS ----------------
class MicrosoftPlannerTasksAPI:
    def __init__(self, access_token: str):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    def get_user_tasks(self, user_email: str) -> List[Dict]:
        """Тодорхой хэрэглэгчийн бүх tasks авах"""
        url = f"{self.base_url}/users/{user_email}/planner/tasks"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            print(f"❌ Tasks авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return []
        
        return response.json().get("value", [])

    def get_all_tasks_from_plan(self, plan_id: str) -> List[Dict]:
        """Тодорхой plan-аас бүх tasks авах"""
        url = f"{self.base_url}/planner/plans/{plan_id}/tasks"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            print(f"❌ Plan tasks авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return []
        
        return response.json().get("value", [])

    def print_tasks_info(self, tasks: List[Dict]):
        """Tasks-ийн мэдээллийг хэвлэх"""
        if not tasks:
            print("❌ Ямар ч task олдсонгүй")
            return
        
        print(f"✅ Нийт {len(tasks)} task олдлоо:")
        print("-" * 80)
        
        for i, task in enumerate(tasks, 1):
            print(f"{i}. {task.get('title', 'Нэргүй')}")
            print(f"   ID: {task.get('id', 'N/A')}")
            print(f"   Төлөв: {task.get('percentComplete', 0)}% дууссан")
            print(f"   Эрэмбэ: {task.get('priority', 'N/A')}")
            
            # Due date
            due_date = task.get('dueDateTime')
            if due_date:
                print(f"   Дуусах хугацаа: {due_date}")
            
            # Assignments
            assignments = task.get('assignments', {})
            if assignments:
                print(f"   Хариуцсан хүн: {len(assignments)} хүн")
            
            print("-" * 40)


# ---------------- MAIN ----------------
def main():
    token = get_access_token()
    planner_api = MicrosoftPlannerTasksAPI(token)
    
    # Сонголт 1: Тодорхой хэрэглэгчийн tasks авах
    print("🔍 tuvshinjargal@fibo.cloud хэрэглэгчийн tasks авч байна...")
    user_tasks = planner_api.get_user_tasks("tuvshinjargal@fibo.cloud")
    planner_api.print_tasks_info(user_tasks)
    
    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()