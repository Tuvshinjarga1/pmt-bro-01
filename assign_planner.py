import requests
import time
import threading
from typing import Dict, List, Optional
import json


# ---------------- CONFIG ----------------
TENANT_ID     = "3fee1c11-7cdf-44b4-a1b0-5183408e1d89"
CLIENT_ID     = "a6e958a7-e8df-4e83-a8c2-5dc73f93bdc4"
CLIENT_SECRET = ""

_cached_token = None
_token_expiry = 0


# ---------------- ACCESS TOKEN ----------------
def get_access_token():
    """Microsoft Graph API-н access token авах"""
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    headers = { "Content-Type": "application/x-www-form-urlencoded" }
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }

    response = requests.post(url, headers=headers, data=data)

    # Алдааны дэлгэрэнгүйг хэвлэнэ
    if response.status_code != 200:
        print("❌ Error details:")
        print("Status code:", response.status_code)
        print("Response body:", response.text)
    
    response.raise_for_status()
    token = response.json().get("access_token")
    return token


def get_cached_access_token() -> str:
    global _cached_token, _token_expiry

    if _cached_token and time.time() < _token_expiry - 10:
        return _cached_token

    token = get_access_token()
    _cached_token = token
    _token_expiry = time.time() + 3600
    return _cached_token


# ---------------- MICROSOFT PLANNER API CLASS ----------------
class MicrosoftPlannerAPI:
    """Microsoft Graph API-г ашиглан Planner-тай ажиллах класс"""
    
    def __init__(self, access_token: str):
        """
        API класс үүсгэх
        
        Args:
            access_token (str): Microsoft Graph API-н access token
        """
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    def get_target_group(self, group_name: str) -> Dict:
        """
        Дэлгэрэнгүй нэрээр групп хайж олох
        
        Args:
            group_name (str): Хайх группын нэр
            
        Returns:
            Dict: Группын мэдээлэл
        """
        url = f"{self.base_url}/groups"
        params = {
            "$filter": f"displayName eq '{group_name}'",
            "$select": "id,displayName"
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        return response.json()
    
    def get_plans_for_group(self, group_id: str) -> Dict:
        """
        Тодорхой группын бүх төлөвлөгөөг авах
        
        Args:
            group_id (str): Группын ID
            
        Returns:
            Dict: Төлөвлөгөөнүүдийн жагсаалт
        """
        url = f"{self.base_url}/groups/{group_id}/planner/plans"
        
        response = requests.get(url, headers=self.headers)
        return response.json()
    
    def create_plan(self, owner_group_id: str, title: str) -> Dict:
        """
        Шинэ төлөвлөгөө үүсгэх
            
        Args:
            owner_group_id (str): Эзэмшигч группын ID
            title (str): Төлөвлөгөөний нэр
            
        Returns:
            Dict: Үүсгэсэн төлөвлөгөөний мэдээлэл
        """
        url = f"{self.base_url}/planner/plans"
        data = {
            "owner": owner_group_id,
            "title": title
        }
        
        response = requests.post(url, headers=self.headers, json=data)
        return response.json()
    
    def get_plan(self, group_id: str, plan_id: str) -> Dict:
        """
        Төлөвлөгөөний дэлгэрэнгүй мэдээлэл авах
        
        Args:
            group_id (str): Группын ID
            plan_id (str): Төлөвлөгөөний ID
            
        Returns:
            Dict: Төлөвлөгөөний мэдээлэл
        """
        url = f"{self.base_url}/groups/{group_id}/planner/plans/{plan_id}"
        
        response = requests.get(url, headers=self.headers)
        return response.json()


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


# ---------------- TASK ASSIGNMENT CLASS ----------------
class TaskAssignmentManager:
    def __init__(self, access_token: str):
        self.planner_api = MicrosoftPlannerAPI(access_token)
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

    def get_plan_details(self, plan_id: str) -> Optional[Dict]:
        """Планын мэдээлэл авах"""
        url = f"{self.base_url}/planner/plans/{plan_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            print("❌ Планын мэдээлэл авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return None
        return response.json()

    def get_group_details(self, group_id: str) -> Optional[Dict]:
        """Группын мэдээлэл авах"""
        url = f"{self.base_url}/groups/{group_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            print("❌ Группын мэдээлэл авахад алдаа гарлаа:")
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



    def get_task_with_url(self, task_id: str) -> Optional[Dict]:
        """Таскын мэдээлэл болон URL-тай хамт авах"""
        task_details = self.get_task_details(task_id)
        if task_details:
            task_url = self.generate_task_url(task_id)
            task_details['web_url'] = task_url
        return task_details

    def unassign_task_from_user(self, task_id: str, user_id: str) -> bool:
        """Таскыг хэрэглэгчээс unassign хийх"""
        try:
            task_details = self.get_task_details(task_id)
            if not task_details:
                return False

            url = f"{self.base_url}/planner/tasks/{task_id}"
            data = {
                "assignments": {
                    user_id: None  # null утга assign-г устгана
                }
            }

            etag = task_details.get("@odata.etag", "")
            headers = self.headers.copy()
            if etag:
                headers["If-Match"] = etag

            response = requests.patch(url, headers=headers, json=data)

            if response.status_code not in [200, 204]:
                print("❌ Таск unassign хийхэд алдаа гарлаа:")
                print("Status code:", response.status_code)
                print("Response:", response.text)
                return False

            return True

        except Exception as e:
            print(f"❌ Таск unassign хийхэд алдаа гарлаа: {str(e)}")
            return False

    def auto_unassign_after_delay(self, task_id: str, user_id: str, delay_seconds: int = 30):
        """Тодорхой хугацааны дараа автоматаар unassign хийх"""
        def unassign_job():
            time.sleep(delay_seconds)
            print(f"\n⏰ {delay_seconds} секунд болсон тул таскыг автоматаар unassign хийж байна...")
            if self.unassign_task_from_user(task_id, user_id):
                print("✅ Таск автоматаар unassign хийгдлээ!")
            else:
                print("❌ Автомат unassign хийхэд алдаа гарлаа")
        
        # Background thread-д ажиллуулах
        thread = threading.Thread(target=unassign_job, daemon=True)
        thread.start()
        print(f"⏱️ {delay_seconds} секундийн дараа автоматаар unassign хийгдэх болно...")

    def assign_task_to_user(self, task_id: str, user_id: str, auto_unassign: bool = False, unassign_delay: int = 30) -> bool:
        try:
            task_details = self.get_task_details(task_id)
            if not task_details:
                return False

            url = f"{self.base_url}/planner/tasks/{task_id}"
            data = {
                "assignments": {
                    user_id: {
                        "@odata.type": "#microsoft.graph.plannerAssignment",
                        "orderHint": " !"
                    }
                }
            }

            etag = task_details.get("@odata.etag", "")
            headers = self.headers.copy()
            if etag:
                headers["If-Match"] = etag

            response = requests.patch(url, headers=headers, json=data)

            if response.status_code not in [200, 204]:
                print("❌ Таск хуваарилахад алдаа гарлаа:")
                print("Status code:", response.status_code)
                print("Response:", response.text)
                return False

            # Хэрэв auto_unassign идэвхжүүлэгдсэн бол автомат unassign эхлүүлэх
            if auto_unassign:
                self.auto_unassign_after_delay(task_id, user_id, unassign_delay)

            return True

        except Exception as e:
            print(f"❌ Таск хуваарилахад алдаа гарлаа: {str(e)}")
            return False

    def print_task_info(self, task: Dict, index: int = None, show_url: bool = False):
        # Зөвхөн дуусаагүй таскуудыг харуулах (100% бус)
        if task.get('percentComplete') != 100:
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
                else:
                    print(f"   🔗 URL: Авах боломжгүй")
            
            print("-" * 40)
        

    def parse_task_selection(self, selection_input: str, max_tasks: int) -> List[int]:
        """Дугаараар таск сонгох функц - жишээ: '1,3,5' эсвэл '1-5' эсвэл 'all'"""
        selected_indices = []
        
        if selection_input.lower() == 'all':
            return list(range(max_tasks))
        
        parts = selection_input.split(',')
        for part in parts:
            part = part.strip()
            if '-' in part:
                # Range хэлбэр: 1-5
                try:
                    start, end = map(int, part.split('-'))
                    start = max(1, start) - 1  # 0-based index
                    end = min(max_tasks, end)  # 1-based to 0-based
                    selected_indices.extend(range(start, end))
                except ValueError:
                    continue
            else:
                # Дан дугаар
                try:
                    index = int(part) - 1  # 0-based index
                    if 0 <= index < max_tasks:
                        selected_indices.append(index)
                except ValueError:
                    continue
        
        return sorted(list(set(selected_indices)))  # Давхардсанийг арилгаж эрэмбэлэх

    def transfer_selected_tasks(self, from_user_email: str, to_user_email: str, task_indices: List[int] = None) -> bool:
        """Сонгосон таскуудыг шилжүүлэх"""
        print("🔄 Таскуудыг шилжүүлж байна...")
        print(f"Эх хэрэглэгч: {from_user_email}")
        print(f"Очих хэрэглэгч: {to_user_email}")
        print("=" * 60)

        from_user = self.users_api.search_user_by_email(from_user_email)
        if not from_user:
            print(f"❌ '{from_user_email}' хэрэглэгч олдсонгүй")
            return False

        to_user = self.users_api.search_user_by_email(to_user_email)
        if not to_user:
            print(f"❌ '{to_user_email}' хэрэглэгч олдсонгүй")
            return False

        self.users_api.print_user_info(from_user, "Эх хэрэглэгч")
        self.users_api.print_user_info(to_user, "Очих хэрэглэгч")

        all_tasks = self.get_user_tasks(from_user.get('id'))
        if not all_tasks:
            print(f"ℹ️ '{from_user_email}' хэрэглэгчид хуваарилагдсан таск байхгүй байна")
            return True

        print(f"\n✅ {len(all_tasks)} таск олдлоо:")
        # print(f"\n✅ {len(all_tasks)} таск олдлоо:")
        for i, task in enumerate(all_tasks, 1):
            self.print_task_info(task, i)

        # Хэрэв task_indices өгөгдөөгүй бол хэрэглэгчээс асуух
        if task_indices is None:
            print("\nТаскууд сонгох заавар:")
            print("- Бүгдийг сонгоход: 'all'")
            print("- Дан дугаар: '3'")
            print("- Олон дугаар: '1,3,5'")
            print("- Range: '1-5'")
            print("- Холимог: '1,3-5,8'")
            
            selection = input(f"\nАль таскуудыг шилжүүлэх вэ? ").strip()
            task_indices = self.parse_task_selection(selection, len(all_tasks))

        if not task_indices:
            print("❌ Таск сонгогдоогүй байна")
            return False

        # Сонгосон таскуудыг харуулах
        selected_tasks = [all_tasks[i] for i in task_indices]
        print(f"\n📋 Сонгосон {len(selected_tasks)} таск:")
        for i, task in enumerate(selected_tasks, 1):
            print(f"{i}. {task.get('title', 'Нэргүй таск')}")

        confirm = input(f"\n{len(selected_tasks)} таскыг '{to_user.get('displayName')}' дээр хуваарилах уу? (y/n): ").lower().strip()
        if confirm != 'y':
            print("❌ Цуцлагдлаа")
            return False

        success_count = 0
        for i, task in enumerate(selected_tasks, 1):
            print(f"\n🔄 Таск {i}/{len(selected_tasks)} шилжүүлж байна: {task.get('title')}")
            if self.assign_task_to_user(task.get('id'), to_user.get('id')):
                print("✅ Таск амжилттай шилжүүлэгдлээ")
                success_count += 1
            else:
                print("❌ Таск шилжүүлэхэд алдаа гарлаа")

        print(f"\n🎉 {success_count}/{len(selected_tasks)} таск амжилттай шилжүүлэгдлээ!")
        return success_count > 0

    def show_user_tasks_with_urls(self, user_email: str) -> bool:
        """Хэрэглэгчийн таскуудыг URL-тай хамт харуулах"""
        print(f"🔍 {user_email} хэрэглэгчийн таскууд:")
        print("=" * 60)

        user = self.users_api.search_user_by_email(user_email)
        if not user:
            print(f"❌ '{user_email}' хэрэглэгч олдсонгүй")
            return False

        self.users_api.print_user_info(user, "Хэрэглэгч")

        tasks = self.get_user_tasks(user.get('id'))
        if not tasks:
            print(f"ℹ️ '{user_email}' хэрэглэгчид хуваарилагдсан таск байхгүй байна")
            return True

        print(f"\n✅ {len(tasks)} таск олдлоо (URL-тай):")
        for i, task in enumerate(tasks, 1):
            self.print_task_info(task, i, show_url=True)

        return True

    def transfer_all_tasks(self, from_user_email: str, to_user_email: str) -> bool:
        print("🔄 Таскуудыг шилжүүлж байна...")
        print(f"Эх хэрэглэгч: {from_user_email}")
        print(f"Очих хэрэглэгч: {to_user_email}")
        print("=" * 60)

        from_user = self.users_api.search_user_by_email(from_user_email)
        if not from_user:
            print(f"❌ '{from_user_email}' хэрэглэгч олдсонгүй")
            return False

        to_user = self.users_api.search_user_by_email(to_user_email)
        if not to_user:
            print(f"❌ '{to_user_email}' хэрэглэгч олдсонгүй")
            return False

        self.users_api.print_user_info(from_user, "Эх хэрэглэгч")
        self.users_api.print_user_info(to_user, "Очих хэрэглэгч")

        tasks = self.get_user_tasks(from_user.get('id'))
        if not tasks:
            print(f"ℹ️ '{from_user_email}' хэрэглэгчид хуваарилагдсан таск байхгүй байна")
            return True

        print(f"\n✅ {len(tasks)} таск олдлоо:")
        for i, task in enumerate(tasks, 1):
            self.print_task_info(task, i)

        confirm = input(f"\n{len(tasks)} таскыг '{to_user.get('displayName')}' дээр хуваарилах уу? (y/n): ").lower().strip()
        if confirm != 'y':
            print("❌ Цуцлагдлаа")
            return False

        success_count = 0
        for i, task in enumerate(tasks, 1):
            print(f"\n🔄 Таск {i}/{len(tasks)} шилжүүлж байна: {task.get('title')}")
            if self.assign_task_to_user(task.get('id'), to_user.get('id')):
                print("✅ Таск амжилттай шилжүүлэгдлээ")
                success_count += 1
            else:
                print("❌ Таск шилжүүлэхэд алдаа гарлаа")

        print(f"\n🎉 {success_count}/{len(tasks)} таск амжилттай шилжүүлэгдлээ!")
        return success_count > 0


# ---------------- MAIN ----------------
def main():
    print("🔄 Таск хуваалцах систем")
    print("=" * 50)

    try:
        token = get_cached_access_token()
        assignment_manager = TaskAssignmentManager(token)

        # Хэрэглэгчээс мэдээлэл авах
        from_email = input("Эх хэрэглэгчийн и-мэйл: ").strip()
        to_email = input("Очих хэрэглэгчийн и-мэйл: ").strip()
        
        if not from_email or not to_email:
            print("❌ И-мэйл оруулаагүй байна")
            return

        # Хэрэглэгчдийг хайх
        from_user = assignment_manager.users_api.search_user_by_email(from_email)
        if not from_user:
            print(f"❌ '{from_email}' хэрэглэгч олдсонгүй")
            return

        to_user = assignment_manager.users_api.search_user_by_email(to_email)
        if not to_user:
            print(f"❌ '{to_email}' хэрэглэгч олдсонгүй")
            return

        # Хэрэглэгчдийн мэдээлэл харуулах
        assignment_manager.users_api.print_user_info(from_user, "Эх хэрэглэгч")
        assignment_manager.users_api.print_user_info(to_user, "Очих хэрэглэгч")

        # Эх хэрэглэгчийн таскуудыг авах
        tasks = assignment_manager.get_user_tasks(from_user.get('id'))
        if not tasks:
            print(f"ℹ️ '{from_email}' хэрэглэгчид хуваарилагдсан таск байхгүй байна")
            return

        # Дуусаагүй таскуудыг шүүх
        incomplete_tasks = [task for task in tasks if task.get('percentComplete') != 100]
        
        # Таскуудыг URL-тай хамт харуулах
        print(f"\n🔍 {from_email} хэрэглэгчийн таскууд:")
        print("=" * 60)
        print(f"\n✅ {len(incomplete_tasks)} дуусаагүй таск олдлоо (URL-тай):")
        
        if not incomplete_tasks:
            print("ℹ️ Дуусаагүй таск байхгүй байна")
            return
            
        task_counter = 1
        for task in incomplete_tasks:
            assignment_manager.print_task_info(task, task_counter, show_url=True)
            task_counter += 1

        # Таскууд сонгох
        print("\nТаскууд сонгох заавар:")
        print("- Бүгдийг сонгоход: 'all'")
        print("- Дан дугаар: '3'")
        print("- Олон дугаар: '1,3,5'")
        print("- Range: '1-5'")
        print("- Холимог: '1,3-5,8'")
        
        selection = input(f"\nАль таскуудыг шилжүүлэх вэ? ").strip()
        task_indices = assignment_manager.parse_task_selection(selection, len(incomplete_tasks))

        if not task_indices:
            print("❌ Таск сонгогдоогүй байна")
            return

        # Сонгосон таскуудыг харуулах
        selected_tasks = [incomplete_tasks[i] for i in task_indices]
        print(f"\n📋 Сонгосон {len(selected_tasks)} таск:")
        for i, task in enumerate(selected_tasks, 1):
            print(f"{i}. {task.get('title', 'Нэргүй таск')}")

        # Автомат unassign сонголт
        auto_unassign = input(f"\nАвтомат unassign хийх үү? (y/n): ").lower().strip() == 'y'
        delay = 30
        if auto_unassign:
            try:
                delay = int(input("Хэдэн секундийн дараа unassign хийх вэ? (default: 30): ") or "30")
                if delay < 1:
                    delay = 30
            except ValueError:
                delay = 30

        # Баталгаажуулах
        if auto_unassign:
            confirm = input(f"\n{len(selected_tasks)} таскыг '{to_user.get('displayName')}' дээр хуваарилж, {delay} секундийн дараа автоматаар unassign хийх үү? (y/n): ").lower().strip()
        else:
            confirm = input(f"\n{len(selected_tasks)} таскыг '{to_user.get('displayName')}' дээр хуваарилах уу? (y/n): ").lower().strip()
            
        if confirm != 'y':
            print("❌ Цуцлагдлаа")
            return

        # Таскуудыг шилжүүлэх
        success_count = 0
        for i, task in enumerate(selected_tasks, 1):
            print(f"\n🔄 Таск {i}/{len(selected_tasks)} шилжүүлж байна: {task.get('title')}")
            if assignment_manager.assign_task_to_user(task.get('id'), to_user.get('id'), auto_unassign=auto_unassign, unassign_delay=delay):
                print("✅ Таск амжилттай шилжүүлэгдлээ")
                # URL харуулах
                task_url = assignment_manager.generate_task_url(task.get('id'))
                if task_url:
                    print(f"🔗 Таскын холбоос: {task_url}")
                success_count += 1
            else:
                print("❌ Таск шилжүүлэхэд алдаа гарлаа")

        print(f"\n🎉 {success_count}/{len(selected_tasks)} таск амжилттай шилжүүлэгдлээ!")
        
        # Автомат unassign хүлээх
        if auto_unassign and success_count > 0:
            print(f"⏲️ {delay} секундийн дараа автоматаар unassign хийгдэх болно...")
            print("ℹ️ Програмыг хаахгүй байгаарай...")
            try:
                time.sleep(delay + 2)  # Unassign болж дуусахыг хүлээх
                print("\n🎉 Бүх үйлдэл дууслаа!")
            except KeyboardInterrupt:
                print("\n⚠️ Програм зогссон, гэхдээ автомат unassign цаана ажиллаж байна...")
    except Exception as e:
        print(f"❌ Алдаа гарлаа: {str(e)}")


if __name__ == "__main__":
    main()