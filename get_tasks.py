import requests
from typing import Dict, List, Optional
import os
import time

# ---------------- CONFIG ----------------
TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

_cached_token = None
_token_expiry = 0

# ---------------- ACCESS TOKEN ----------------
def get_access_token() -> str:
    """Microsoft Graph API-д хандах token авах"""
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
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
    return token_data["access_token"]

def get_cached_access_token() -> str:
    global _cached_token, _token_expiry

    if _cached_token and time.time() < _token_expiry - 10:
        return _cached_token

    token = get_access_token()
    _cached_token = token
    _token_expiry = time.time() + 3600
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
        from urllib.parse import quote
        encoded_email = quote(email)
        url = f"{self.base_url}/users?$select=id,displayName,mail,jobTitle,department,accountEnabled&$filter=mail eq '{encoded_email}'"
        response = requests.get(url, headers=self.headers)

        if response.status_code != 200:
            print("❌ Хэрэглэгч хайхад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return None

        users = response.json().get("value", [])
        return users[0] if users else None

    def print_user_info(self, user: Dict, title: str = "Хэрэглэгчийн мэдээлэл"):
        print(f"\n{title}:")
        print("-" * 50)
        print(f"Нэр: {user.get('displayName', 'N/A')}")
        print(f"И-мэйл: {user.get('mail', 'N/A')}")
        print(f"Албан тушаал: {user.get('jobTitle', 'N/A')}")
        print(f"Хэлтэс: {user.get('department', 'N/A')}")
        print(f"ID: {user.get('id', 'N/A')}")
        print(f"Account enabled: {'✅ Yes' if user.get('accountEnabled', True) else '❌ No'}")

# ---------------- PLANNER TASKS CLASS ----------------
class MicrosoftPlannerTasksAPI:
    """Хэрэглэгчийн Planner таскууд болон таскын URL авах энгийн API"""
    def __init__(self, access_token: str):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def get_user_tasks(self, user_email: str) -> List[Dict]:
        """Хэрэглэгчийн planner таскуудыг авах"""
        url = f"{self.base_url}/users/{user_email}/planner/tasks"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            print("❌ Таскууд авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return []
        return response.json().get("value", [])

    def get_task_details(self, task_id: str) -> Optional[Dict]:
        url = f"{self.base_url}/planner/tasks/{task_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            print("❌ Таскын мэдээлэл авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return None
        return response.json()

    def generate_task_url(self, task_id: str) -> Optional[str]:
        """Planner таскын веб URL (шинэ формат) гаргаж авах"""
        try:
            task_details = self.get_task_details(task_id)
            if not task_details:
                return None
            plan_id = task_details.get("planId")
            if not plan_id:
                return None
            return f"https://planner.cloud.microsoft/webui/plan/{plan_id}/view/board/task/{task_id}?tid={TENANT_ID}"
        except Exception as exc:
            print(f"❌ URL үүсгэхэд алдаа гарлаа: {exc}")
            return None

# ---------------- TASK ASSIGNMENT CLASS ----------------
class TaskAssignmentManager:
    def __init__(self, access_token: str):
        self.users_api = MicrosoftUsersAPI(access_token)
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    def get_user_tasks(self, user_id: str) -> List[Dict]:
        url = f"{self.base_url}/users/{user_id}/planner/tasks"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            print("❌ Таскууд авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return []
        return response.json().get("value", [])

    def get_task_details(self, task_id: str) -> Optional[Dict]:
        url = f"{self.base_url}/planner/tasks/{task_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            print("❌ Таскын мэдээлэл авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return None
        return response.json()

    def generate_task_url(self, task_id: str) -> Optional[str]:
        """Таскын веб URL үүсгэх"""
        try:
            task_details = self.get_task_details(task_id)
            if not task_details:
                return None

            plan_id = task_details.get('planId')
            if not plan_id:
                return None

            # Microsoft Planner Task URL format (шинэ формат):
            # https://planner.cloud.microsoft/webui/plan/{plan-id}/view/board/task/{task-id}?tid={tenant-id}
            tenant_id = TENANT_ID
            task_url = f"https://planner.cloud.microsoft/webui/plan/{plan_id}/view/board/task/{task_id}?tid={tenant_id}"
            
            return task_url

        except Exception as e:
            print(f"❌ URL үүсгэхэд алдаа гарлаа: {str(e)}")
            return None

    def print_task_info(self, task: Dict, index: int = None, show_url: bool = False):
        prefix = f"{index}. " if index is not None else ""
        print(f"{prefix}📋 {task.get('title', 'Нэргүй таск')}")
        print(f"   ID: {task.get('id', 'N/A')}")
        print(f"   Төлөв: {task.get('percentComplete', 0)}%")
        print(f"   Тэргүүлэх эрэмбэ: {task.get('priority', 'N/A')}")
        print(f"   Дуусах огноо: {task.get('dueDateTime', 'N/A')}")
        print(f"   Хуваарилагдсан: {len(task.get('assignments', {}))} хүн")
        
        if show_url:
            task_url = self.generate_task_url(task.get('id'))
            if task_url:
                print(f"   🔗 Таскын URL: {task_url}")
                
                # Планын URL ч харуулах
                # task_details = self.get_task_details(task.get('id'))
                # if task_details and task_details.get('planId'):
                #     plan_url = self.generate_plan_url(task_details.get('planId'))
                #     print(f"   📋 Планын URL: {plan_url}")
            else:
                print(f"   🔗 URL: Авах боломжгүй")
        
        print("-" * 40)

    def get_user_tasks_with_urls(self, user_email: str) -> List[Dict]:
        """Хэрэглэгчийн дуусаагүй таскуудыг URL-тай хамт буцаах"""
        user = self.users_api.search_user_by_email(user_email)
        if not user:
            print(f"❌ '{user_email}' хэрэглэгч олдсонгүй")
            return []

        all_tasks = self.get_user_tasks(user.get('id'))
        if not all_tasks:
            print(f"ℹ️ '{user_email}' хэрэглэгчид хуваарилагдсан таск байхгүй байна")
            return []

        # Зөвхөн 100% дуусаагүй таскуудыг шүүх
        incomplete_tasks = [task for task in all_tasks if task.get('percentComplete', 0) < 100]
        
        if not incomplete_tasks:
            print(f"ℹ️ '{user_email}' хэрэглэгчид дуусаагүй таск байхгүй байна (бүх таск 100% дууссан)")
            return []

        # URL-уудыг нэмэх
        tasks_with_urls = []
        for task in incomplete_tasks:
            task_url = self.generate_task_url(task.get('id'))
            task_with_url = {
                **task,
                'task_url': task_url
            }
            tasks_with_urls.append(task_with_url)

        return tasks_with_urls

    def show_user_tasks_with_urls(self, user_email: str) -> bool:
        """Хэрэглэгчийн таскуудыг URL-тай хамт харуулах (зөвхөн дуусаагүй таскууд)"""
        print(f"🔍 {user_email} хэрэглэгчийн дуусаагүй таскууд:")
        print("=" * 60)

        user = self.users_api.search_user_by_email(user_email)
        if not user:
            print(f"❌ '{user_email}' хэрэглэгч олдсонгүй")
            return False

        self.users_api.print_user_info(user, "Хэрэглэгч")

        all_tasks = self.get_user_tasks(user.get('id'))
        if not all_tasks:
            print(f"ℹ️ '{user_email}' хэрэглэгчид хуваарилагдсан таск байхгүй байна")
            return True

        # Зөвхөн 100% дуусаагүй таскуудыг шүүх
        incomplete_tasks = [task for task in all_tasks if task.get('percentComplete', 0) < 100]
        
        if not incomplete_tasks:
            print(f"ℹ️ '{user_email}' хэрэглэгчид дуусаагүй таск байхгүй байна (бүх таск 100% дууссан)")
            return True

        print(f"\n✅ {len(incomplete_tasks)} дуусаагүй таск олдлоо (URL-тай):")
        for i, task in enumerate(incomplete_tasks, 1):
            self.print_task_info(task, i, show_url=True)

        return True

# ---------------- MAIN ----------------
def main():
    print("🔍 Хэрэглэгчийн дуусаагүй таскуудыг URL-тай хамт харах")
    print("=" * 60)

    try:
        token = get_cached_access_token()
        assignment_manager = TaskAssignmentManager(token)

        # Хэрэглэгчийн таскуудыг URL-тай хамт харах
        user_email = input("Хэрэглэгчийн и-мэйл: ").strip()
        if not user_email:
            print("❌ И-мэйл оруулаагүй байна")
            return

        # Харах эсвэл буцаах сонголт
        choice = input("1. Харах, 2. Буцаах (1/2): ").strip()
        
        if choice == "2":
            # Таскуудыг URL-тай хамт буцаах
            tasks_with_urls = assignment_manager.get_user_tasks_with_urls(user_email)
            if tasks_with_urls:
                print(f"\n✅ {len(tasks_with_urls)} таск URL-тай хамт буцаагдалаа:")
                for i, task in enumerate(tasks_with_urls, 1):
                    print(f"{i}. {task.get('title')} - {task.get('task_url')}")
            return
        
        # Анхдагч функц - харах
        assignment_manager.show_user_tasks_with_urls(user_email)
        
    except Exception as e:
        print(f"❌ Алдаа гарлаа: {str(e)}")

if __name__ == "__main__":
    main()