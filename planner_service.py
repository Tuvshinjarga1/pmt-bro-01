"""
Microsoft Graph API service for accessing planner tasks using client credentials
"""

import requests
import time
from typing import Dict, List, Optional
from config import Config

# Global variables for token caching
_cached_token = None
_token_expiry = 0

def get_access_token() -> str:
    """Get access token using client credentials"""
    global _cached_token, _token_expiry
    
    config = Config()
    TENANT_ID = config.GRAPH_TENANT_ID
    CLIENT_ID = config.GRAPH_CLIENT_ID
    CLIENT_SECRET = config.GRAPH_CLIENT_SECRET

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

class PlannerService:
    """Service to interact with Microsoft Graph API for planner tasks"""
    
    def __init__(self):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.access_token = get_access_token()
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def get_user_incomplete_tasks(self, user_email: str) -> List[Dict]:
        """Тодорхой хэрэглэгчийн дутуу tasks авах"""
        url = f"{self.base_url}/users/{user_email}/planner/tasks"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            print(f"❌ User tasks авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            return []
        
        tasks = response.json().get("value", [])
        
        # Filter incomplete tasks (less than 100% complete)
        incomplete_tasks = []
        for task in tasks:
            if task.get("percentComplete", 0) < 100:
                incomplete_tasks.append({
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "planTitle": "Planner Task",
                    "dueDateTime": task.get("dueDateTime"),
                    "percentComplete": task.get("percentComplete", 0),
                    "priority": task.get("priority", 5),
                    "createdDateTime": task.get("createdDateTime")
                })
        
        return incomplete_tasks

    def get_personal_tasks(self, user_email: str) -> List[Dict]:
        """Microsoft To-Do tasks авах"""
        # Get user's to-do lists
        lists_url = f"{self.base_url}/users/{user_email}/todo/lists"
        response = requests.get(lists_url, headers=self.headers)
        
        if response.status_code != 200:
            print(f"❌ To-Do lists авахад алдаа гарлаа:")
            print("Status code:", response.status_code)
            return []
        
        task_lists = response.json().get("value", [])
        incomplete_tasks = []
        
        # Get tasks from each list
        for task_list in task_lists:
            list_id = task_list.get("id")
            list_name = task_list.get("displayName")
            
            if list_id:
                tasks_url = f"{self.base_url}/users/{user_email}/todo/lists/{list_id}/tasks"
                tasks_response = requests.get(tasks_url, headers=self.headers)
                
                if tasks_response.status_code == 200:
                    tasks = tasks_response.json().get("value", [])
                    
                    # Filter incomplete tasks
                    for task in tasks:
                        if task.get("status") != "completed":
                            incomplete_tasks.append({
                                "id": task.get("id"),
                                "title": task.get("title"),
                                "listName": list_name,
                                "dueDateTime": task.get("dueDateTime", {}).get("dateTime") if task.get("dueDateTime") else None,
                                "importance": task.get("importance"),
                                "createdDateTime": task.get("createdDateTime"),
                                "status": task.get("status")
                            })
        
        return incomplete_tasks

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

    def format_tasks_for_display(self, planner_tasks: List[Dict], personal_tasks: List[Dict]) -> str:
        """Даалгаваруудыг харуулахад тохиромжтой форматаар бэлтгэх"""
        
        if not planner_tasks and not personal_tasks:
            return "✅ Танд дутуу даалгавар алга байна! 🎉"
        
        result = []
        
        # Planner tasks
        if planner_tasks:
            result.append("📋 **Microsoft Planner даалгаврууд:**\n")
            for i, task in enumerate(planner_tasks, 1):
                priority = task.get("priority", 5)
                priority_emoji = "🔴" if priority <= 3 else "🟡" if priority <= 6 else "🔵"
                
                title = task.get("title", "Нэргүй даалгавар")
                percent = task.get("percentComplete", 0)
                
                due_info = ""
                if task.get("dueDateTime"):
                    due_info = f"⏰ {task['dueDateTime'][:10]}"
                
                result.append(f"{i}. {priority_emoji} **{title}**")
                result.append(f"биелэлт📊 {percent}% {due_info}")
                result.append("")
        
        # Personal To-Do tasks  
        if personal_tasks:
            result.append("📝 **Хувийн даалгаврууд (To-Do):**\n")
            for i, task in enumerate(personal_tasks, 1):
                importance = task.get("importance", "normal")
                importance_emoji = "🔴" if importance == "high" else "🟡" if importance == "normal" else "🔵"
                
                title = task.get("title", "Нэргүй даалгавар")
                list_name = task.get("listName", "Жагсаалт")
                
                due_info = ""
                if task.get("dueDateTime"):
                    due_info = f"⏰ {task['dueDateTime'][:10]}"
                
                result.append(f"{i}. {importance_emoji} **{title}**")
                result.append(f"   📁 {list_name} {due_info}")
                result.append("")
        
        result.append("💡 *Даалгавраа дуусгахын тулд Microsoft Teams эсвэл Planner app ашиглана уу.*")
        
        return "\n".join(result)

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