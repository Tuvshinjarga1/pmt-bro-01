"""
Organization Service - Хэрэглэгчийн лидэр, багийн мэдээлэл авах
"""

import requests
from typing import Dict, Optional, List
from config import Config
from planner_service import get_access_token

class OrganizationService:
    """Байгууллагын бүтэц болон хэрэглэгчийн мэдээлэл авах сервис"""
    
    def __init__(self):
        try:
            self.base_url = "https://graph.microsoft.com/v1.0"
            self.access_token = get_access_token()
            
            if not self.access_token:
                print("⚠️ Graph API token авахад алдаа гарлаа")
                self.headers = None
            else:
                self.headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }
                
        except Exception as e:
            print(f"❌ Organization service эхлүүлэхэд алдаа: {str(e)}")
            self.headers = None
    
    def get_user_manager(self, user_email: str) -> Optional[Dict]:
        """Хэрэглэгчийн лидэрийн мэдээлэл авах"""
        
        if not self.headers:
            print("❌ Graph API headers алга байна")
            return None
            
        try:
            url = f"{self.base_url}/users/{user_email}/manager"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                manager_data = response.json()
                return {
                    "id": manager_data.get("id"),
                    "displayName": manager_data.get("displayName"),
                    "mail": manager_data.get("mail"),
                    "jobTitle": manager_data.get("jobTitle"),
                    "department": manager_data.get("department")
                }
            elif response.status_code == 404:
                print(f"Хэрэглэгч {user_email}-н лидэр олдсонгүй")
                return None
            else:
                print(f"❌ Manager мэдээлэл авахад алдаа: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Manager мэдээлэл авахад алдаа: {str(e)}")
            return None
    
    def get_user_team_members(self, user_email: str) -> List[Dict]:
        """Хэрэглэгчтэй нэг багт ажилладаг хүмүүсийн жагсаалт"""
        
        if not self.headers:
            print("❌ Graph API headers алга байна")
            return []
            
        try:
            # Эхлээд хэрэглэгчийн лидэрийг олох
            manager = self.get_user_manager(user_email)
            if not manager:
                return []
            
            # Лидэрийн дор ажилладаг хүмүүсийг олох
            manager_id = manager.get("id")
            url = f"{self.base_url}/users/{manager_id}/directReports"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                team_data = response.json().get("value", [])
                team_members = []
                
                for member in team_data:
                    team_members.append({
                        "id": member.get("id"),
                        "displayName": member.get("displayName"),
                        "mail": member.get("mail"),
                        "jobTitle": member.get("jobTitle")
                    })
                
                return team_members
            else:
                print(f"❌ Team members мэдээлэл авахад алдаа: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"❌ Team members мэдээлэл авахад алдаа: {str(e)}")
            return []
    
    def get_user_profile(self, user_email: str) -> Optional[Dict]:
        """Хэрэглэгчийн дэлгэрэнгүй мэдээлэл авах"""
        
        if not self.headers:
            print("❌ Graph API headers алга байна")
            return None
            
        try:
            url = f"{self.base_url}/users/{user_email}"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                user_data = response.json()
                return {
                    "id": user_data.get("id"),
                    "displayName": user_data.get("displayName"),
                    "mail": user_data.get("mail"),
                    "jobTitle": user_data.get("jobTitle"),
                    "department": user_data.get("department"),
                    "officeLocation": user_data.get("officeLocation"),
                    "mobilePhone": user_data.get("mobilePhone"),
                    "businessPhones": user_data.get("businessPhones", [])
                }
            else:
                print(f"❌ User profile авахад алдаа: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ User profile авахад алдаа: {str(e)}")
            return None
    
    def format_leave_notification_for_manager(self, leave_request: Dict, user_profile: Dict = None) -> Dict:
        """Лидэрт илгээх чөлөөний мэдэгдлийг форматлах"""
        
        user_email = leave_request.get("user_email", "Тодорхойгүй")
        start_date = leave_request.get("start_date", "Тодорхойгүй")
        end_date = leave_request.get("end_date", "Тодорхойгүй")
        reason = leave_request.get("reason", "Шалтгаан дурдаагүй")
        hours = leave_request.get("in_active_hours", 8.0)
        
        # Хэрэглэгчийн нэр
        display_name = user_profile.get("displayName", user_email) if user_profile else user_email
        job_title = user_profile.get("jobTitle", "") if user_profile else ""
        
        notification = {
            "text": f"🏖️ **Чөлөөний хүсэлт**\n\n"
                   f"👤 **Хүсэлт илгээсэн:** {display_name}\n"
                   f"📧 **И-мэйл:** {user_email}\n"
        }
        
        if job_title:
            notification["text"] += f"💼 **Албан тушаал:** {job_title}\n"
        
        notification["text"] += (
            f"📅 **Эхлэх өдөр:** {start_date}\n"
            f"📅 **Дуусах өдөр:** {end_date}\n"
            f"⏰ **Нийт цаг:** {hours} цаг\n"
            f"📝 **Шалтгаан:** {reason}\n\n"
            f"💡 Энэ хүсэлтийг Teams дотроос шийдвэрлэх боломжтой."
        )
        
        return notification 