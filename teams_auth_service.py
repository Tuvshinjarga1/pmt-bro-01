"""
Teams Authentication and Messaging Service
"""

import requests
import json
from typing import Dict, Optional
from config import Config

class TeamsAuthService:
    """Teams мессеж илгээх сервис"""
    
    def __init__(self):
        config = Config()
        self.webhook_url = config.TEAMS_WEBHOOK_URL
        
    def send_leave_request_to_manager(self, leave_request: Dict) -> bool:
        """
        Лидэрт чөлөөний хүсэлт илгээх
        """
        try:
            # Leave request мэдээллийг форматлах
            message = self._format_leave_request_message(leave_request)
            
            # Teams webhook-аар мессеж илгээх
            success = self._send_teams_message(message)
            
            return success
            
        except Exception as e:
            print(f"Teams мессеж илгээхэд алдаа: {str(e)}")
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
            headers = {
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                self.webhook_url,
                headers=headers,
                data=json.dumps(message),
                timeout=10
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