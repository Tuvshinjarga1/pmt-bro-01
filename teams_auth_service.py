"""
Teams Authentication and Messaging Service
"""

import requests
import json
from typing import Dict, Optional
from datetime import datetime
from config import Config

class TeamsAuthService:
    """Teams мессеж илгээх сервис"""
    
    def __init__(self):
        try:
            config = Config()
            self.webhook_url = config.TEAMS_WEBHOOK_URL
            
            if not self.webhook_url:
                print("❌ Teams webhook URL тохируулаагүй байна")
                
        except Exception as e:
            print(f"❌ Teams auth service эхлүүлэхэд алдаа: {str(e)}")
            self.webhook_url = None
        
    def send_leave_request_to_manager(self, leave_request: Dict, manager_email: str = None, user_tasks: str = None) -> bool:
        """
        Лидэрт чөлөөний хүсэлт илгээх (Direct Message эсвэл Channel)
        """
        try:
            if manager_email:
                # Direct message лидэрт илгээх
                success = self._send_direct_message_to_manager(leave_request, manager_email, user_tasks)
            else:
                # Channel дээр webhook илгээх (fallback)
                message = self._format_leave_request_message(leave_request)
                success = self._send_teams_message(message)
            
            return success
            
        except Exception as e:
            print(f"Teams мессеж илгээхэд алдаа: {str(e)}")
            return False
    
    def _send_direct_message_to_manager(self, leave_request: Dict, manager_email: str, user_tasks: str = None) -> bool:
        """Лидэрт direct message илгээх"""
        
        try:
            from planner_service import get_access_token
            access_token = get_access_token()
            
            if not access_token:
                print("❌ Graph API token алга байна")
                return False
            
            user_email = leave_request.get("user_email", "Тодорхойгүй")
            start_date = leave_request.get("start_date", "Тодорхойгүй")
            end_date = leave_request.get("end_date", "Тодорхойгүй")
            reason = leave_request.get("reason", "Шалтгаан дурдаагүй")
            hours = leave_request.get("in_active_hours", 8.0)
            
            # Message body with tasks
            message_body = f"""
🏖️ **Чөлөөний хүсэлт**

👤 **Хүсэлт илгээсэн:** {user_email}
📅 **Эхлэх өдөр:** {start_date}
📅 **Дуусах өдөр:** {end_date}
⏰ **Нийт цаг:** {hours} цаг
📝 **Шалтгаан:** {reason}

📋 **Тухайн хэрэглэгчийн одоогийн дутуу даалгаврууд:**

{user_tasks if user_tasks else "✅ Дутуу даалгавар алга байна"}

---

Та энэ хүсэлтийг зөвшөөрөх эсвэл татгалзах вэ?

**Зөвшөөрөх:** Хариу мессежээр "APPROVE {user_email}" гэж бичнэ үү
**Татгалзах:** Хариу мессежээр "REJECT {user_email} шалтгаан" гэж бичнэ үү
            """
            
            # Graph API дуудах - лидэрт direct message илгээх
            chat_url = "https://graph.microsoft.com/v1.0/chats"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            # Chat үүсгэх эсвэл олох
            chat_data = {
                "chatType": "oneOnOne",
                "members": [
                    {
                        "@odata.type": "#microsoft.graph.aadUserConversationMember",
                        "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{manager_email}')"
                    }
                ]
            }
            
            chat_response = requests.post(chat_url, headers=headers, json=chat_data, timeout=15)
            
            if chat_response.status_code == 201:
                chat_id = chat_response.json().get("id")
                
                # Message илгээх
                message_url = f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages"
                message_data = {
                    "body": {
                        "contentType": "text",
                        "content": message_body
                    }
                }
                
                message_response = requests.post(message_url, headers=headers, json=message_data, timeout=15)
                
                if message_response.status_code == 201:
                    print("✅ Лидэрт direct message амжилттай илгээлээ")
                    return True
                else:
                    print(f"❌ Message илгээхэд алдаа: {message_response.status_code}")
                    return False
            else:
                print(f"❌ Chat үүсгэхэд алдаа: {chat_response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Direct message илгээхэд алдаа: {str(e)}")
            return False
    
    def _format_leave_request_message(self, leave_request: Dict) -> Dict:
        """Чөлөөний хүсэлтийг Teams мессеж форматаар бэлтгэх"""
        
        user_email = leave_request.get("user_email", "Тодорхойгүй хэрэглэгч")
        start_date = leave_request.get("start_date", "Тодорхойгүй")
        end_date = leave_request.get("end_date", "Тодорхойгүй") 
        reason = leave_request.get("reason", "Шалтгаан дурдаагүй")
        hours = leave_request.get("in_active_hours", 8.0)
        
        # Teams Adaptive Card формат
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "0076D7",
            "summary": f"Чөлөөний хүсэлт - {user_email}",
            "sections": [
                {
                    "activityTitle": "🏖️ Шинэ чөлөөний хүсэлт",
                    "activitySubtitle": f"Хүсэлт илгээсэн: {user_email}",
                    "activityImage": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQy5U8Q8Q8Q8Q8Q8Q8Q8Q8Q8Q8Q8Q8Q8Q8Q8Q8",
                    "facts": [
                        {
                            "name": "👤 Хүсэлт илгээсэн:",
                            "value": user_email
                        },
                        {
                            "name": "📅 Эхлэх өдөр:",
                            "value": start_date
                        },
                        {
                            "name": "📅 Дуусах өдөр:",  
                            "value": end_date
                        },
                        {
                            "name": "⏰ Нийт цаг:",
                            "value": f"{hours} цаг"
                        },
                        {
                            "name": "📝 Шалтгаан:",
                            "value": reason
                        }
                    ],
                    "markdown": True
                }
            ],
            "potentialAction": [
                {
                    "@type": "ActionCard",
                    "name": "✅ Зөвшөөрөх",
                    "inputs": [
                        {
                            "@type": "TextInput",
                            "id": "comment",
                            "isMultiline": True,
                            "title": "Тэмдэглэл (заавал биш)"
                        }
                    ],
                    "actions": [
                        {
                            "@type": "HttpPOST",
                            "name": "Зөвшөөрөх",
                            "target": f"{self._get_callback_url()}/approve",
                            "body": json.dumps({
                                "user_email": user_email,
                                "action": "approve",
                                "comment": "{{comment.value}}"
                            })
                        }
                    ]
                },
                {
                    "@type": "ActionCard", 
                    "name": "❌ Татгалзах",
                    "inputs": [
                        {
                            "@type": "TextInput",
                            "id": "reason",
                            "isMultiline": True,
                            "title": "Татгалзах шалтгаан"
                        }
                    ],
                    "actions": [
                        {
                            "@type": "HttpPOST",
                            "name": "Татгалзах",
                            "target": f"{self._get_callback_url()}/reject",
                            "body": json.dumps({
                                "user_email": user_email,
                                "action": "reject", 
                                "reason": "{{reason.value}}"
                            })
                        }
                    ]
                }
            ]
        }
        
        return card
    
    def _send_teams_message(self, message: Dict) -> bool:
        """Teams webhook-аар мессеж илгээх"""
        
        try:
            if not self.webhook_url:
                print("❌ Teams webhook URL алга байна")
                return False
                
            headers = {
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                self.webhook_url,
                headers=headers,
                data=json.dumps(message),
                timeout=15
            )
            
            if response.status_code == 200:
                print("✅ Teams мессеж амжилттай илгээлээ")
                return True
            else:
                print(f"❌ Teams мессеж илгээхэд алдаа: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Teams мессеж илгээхэд алдаа: {str(e)}")
            return False
    
    def _get_callback_url(self) -> str:
        """Callback URL олох"""
        # Одоогоор placeholder, хожим бодит URL тохируулах
        return "https://your-bot-url.com/api/leave-callback"
    
    def send_simple_notification(self, title: str, message: str) -> bool:
        """Энгийн мэдэгдэл илгээх"""
        
        simple_card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions", 
            "themeColor": "0076D7",
            "summary": title,
            "sections": [
                {
                    "activityTitle": title,
                    "text": message,
                    "markdown": True
                }
            ]
        }
        
        return self._send_teams_message(simple_card)
    
    def announce_leave_approval(self, user_email: str, user_name: str, start_date: str, end_date: str) -> bool:
        """Channel дээр чөлөө зөвшөөрөгдсөн тухай зарлах"""
        
        announcement = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "28a745",  # Green color
            "summary": f"Чөлөө зөвшөөрөгдлөө - {user_name}",
            "sections": [
                {
                    "activityTitle": "✅ Чөлөө зөвшөөрөгдлөө",
                    "activitySubtitle": f"{user_name} чөлөө авч байна",
                    "facts": [
                        {
                            "name": "👤 Хэрэглэгч:",
                            "value": user_name
                        },
                        {
                            "name": "📅 Хугацаа:",
                            "value": f"{start_date} - {end_date}"
                        },
                        {
                            "name": "🕐 Цаг:",
                            "value": f"{((datetime.strptime(end_date, '%Y-%m-%d') - datetime.strptime(start_date, '%Y-%m-%d')).days + 1) * 8} цаг"
                        }
                    ],
                    "markdown": True
                }
            ]
        }
        
        return self._send_teams_message(announcement)
    
    def announce_leave_rejection(self, user_email: str, user_name: str, reason: str) -> bool:
        """Channel дээр чөлөө татгалзсан тухай зарлах"""
        
        announcement = {
            "@type": "MessageCard", 
            "@context": "http://schema.org/extensions",
            "themeColor": "dc3545",  # Red color
            "summary": f"Чөлөө татгалзагдлаа - {user_name}",
            "sections": [
                {
                    "activityTitle": "❌ Чөлөө татгалзагдлаа",
                    "activitySubtitle": f"{user_name}-н хүсэлт татгалзагдлаа",
                    "facts": [
                        {
                            "name": "👤 Хэрэглэгч:",
                            "value": user_name
                        },
                        {
                            "name": "📝 Шалтгаан:",
                            "value": reason
                        }
                    ],
                    "markdown": True
                }
            ]
        }
        
        return self._send_teams_message(announcement) 