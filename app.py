import os
import logging
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext, MessageFactory
from botbuilder.schema import Activity, Attachment
import asyncio
import json
from botbuilder.schema import ConversationReference
import re
from datetime import datetime, timedelta
import uuid
import openai
from openai import OpenAI
from config import Config
import requests

# Microsoft Planner tasks авах
try:
    from get_tasks import get_access_token, MicrosoftPlannerTasksAPI
    PLANNER_AVAILABLE = True
except ImportError:
    PLANNER_AVAILABLE = False
    logging.warning("get_tasks module not found. Planner functionality disabled.")

# Logging тохиргоо
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI тохиргоо
openai_client = OpenAI(
    api_key=Config.OPENAI_API_KEY if hasattr(Config, 'OPENAI_API_KEY') else os.getenv("OPENAI_API_KEY", "")
)

# Bot Framework тохиргоо
app_id = os.getenv("MICROSOFT_APP_ID", "")
app_password = os.getenv("MICROSOFT_APP_PASSWORD", "")

logger.info(f"Bot starting with App ID: {app_id[:10]}..." if app_id else "No App ID")

SETTINGS = BotFrameworkAdapterSettings(app_id, app_password)
ADAPTER = BotFrameworkAdapter(SETTINGS)

app = Flask(__name__)

# Хэрэглэгчийн conversation reference хадгалах directory үүсгэх
CONVERSATION_DIR = "conversations"
LEAVE_REQUESTS_DIR = "leave_requests"
PENDING_CONFIRMATIONS_DIR = "pending_confirmations"

for directory in [CONVERSATION_DIR, LEAVE_REQUESTS_DIR, PENDING_CONFIRMATIONS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# Approval хийх хүний мэдээлэл (Bayarmunkh)
APPROVER_EMAIL = "bayarmunkh@fibo.cloud"
APPROVER_USER_ID = "29:1kIuFRh3SgMXCUqtZSJBjHDaDmVF7l2-zXmi3qZNRBokdrt8QxiwyVPutdFsMKMp1R-tF52PqrhmqHegty9X2JA"

def create_approval_card(request_data):
    """Approval-ын тулд adaptive card үүсгэх"""
    card = {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "🏖️ Чөлөөний хүсэлт",
                "weight": "bolder",
                "size": "large",
                "color": "accent"
            },
            {
                "type": "FactSet",
                "facts": [
                    {
                        "title": "Хүсэлт гаргагч:",
                        "value": request_data.get("requester_name", "N/A")
                    },
                    {
                        "title": "Эхлэх өдөр:",
                        "value": request_data.get("start_date", "N/A")
                    },
                    {
                        "title": "Дуусах өдөр:",
                        "value": request_data.get("end_date", "N/A")
                    },
                    {
                        "title": "Хоногийн тоо:",
                        "value": str(request_data.get("days", "N/A"))
                    },
                    {
                        "title": "Цагийн тоо:",
                        "value": f"{request_data.get('inactive_hours', 'N/A')} цаг"
                    },
                    {
                        "title": "Шалтгаан:",
                        "value": request_data.get("reason", "Тодорхойгүй")
                    }
                ]
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Зөвшөөрөх",
                "data": {
                    "action": "approve",
                    "request_id": request_data.get("request_id")
                },
                "style": "positive"
            },
            {
                "type": "Action.Submit", 
                "title": "❌ Татгалзах",
                "data": {
                    "action": "reject",
                    "request_id": request_data.get("request_id")
                },
                "style": "destructive"
            }
        ]
    }
    return card

def get_user_planner_tasks(user_email):
    """Хэрэглэгчийн Microsoft Planner tasks авах"""
    if not PLANNER_AVAILABLE:
        return "📋 Planner модуль идэвхгүй байна"
    
    try:
        # Access token авах
        token = get_access_token()
        planner_api = MicrosoftPlannerTasksAPI(token)
        
        # Хэрэглэгчийн tasks авах
        tasks = planner_api.get_user_tasks(user_email)
        
        if not tasks:
            return "📋 Planner-д идэвхтэй task олдсонгүй"
        
        # Tasks-ийн мэдээллийг форматлах
        tasks_info = f"📋 **{user_email} - Planner Tasks ({len(tasks)} task):**\n\n"
        
        # Зөвхөн идэвхтэй (дуусаагүй) tasks харуулах
        active_tasks = [task for task in tasks if task.get('percentComplete', 0) < 100]
        
        if not active_tasks:
            return "📋 Planner-д дуусаагүй task олдсонгүй"
        
        for i, task in enumerate(active_tasks[:5], 1):  # Зөвхөн эхний 5-г харуулах
            title = task.get('title', 'Нэргүй task')
            progress = task.get('percentComplete', 0)
            priority = task.get('priority', 'N/A')
            
            # Due date форматлах
            due_date = task.get('dueDateTime')
            due_text = ""
            if due_date:
                try:
                    # ISO datetime парс хийх
                    dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                    due_text = f" 📅 {dt.strftime('%m/%d')}"
                except:
                    due_text = f" 📅 {due_date[:10]}"
            
            priority_emoji = "🔴" if priority == "urgent" else "🟡" if priority == "important" else "🔵"
            progress_text = f"{progress}%" if progress > 0 else "0%"
            
            tasks_info += f"{i}. {priority_emoji} **{title}**\n"
            tasks_info += f"   📊 {progress_text} дууссан{due_text}\n\n"
        
        if len(active_tasks) > 5:
            tasks_info += f"... болон {len(active_tasks) - 5} бусад task\n"
        
        return tasks_info.strip()
        
    except Exception as e:
        logger.error(f"Failed to get planner tasks for {user_email}: {str(e)}")
        return f"📋 Planner tasks авахад алдаа: {str(e)}"

async def call_external_absence_api(request_data):
    """External API руу absence request үүсгэх дуудлага хийх"""
    try:
        api_url = "https://mcp-server-production-6219.up.railway.app/call-function"
        
        # API payload бэлтгэх
        # payload = {
        #     "function": "create_absence_request",
        #     "args": {
        #         "user_email": request_data.get("requester_email"),
        #         "start_date": request_data.get("start_date"),
        #         "end_date": request_data.get("end_date"),
        #         "reason": request_data.get("reason", ""),
        #         "in_active_hours": request_data.get("inactive_hours", 8)
        #     }
        # }
        
        payload = {
            "function": "create_absence_request",
            "args": {
                "user_email": "test_user10@fibo.cloud",
                "start_date": "2025-07-30",
                "end_date": "2025-07-31",
                "reason": "test",
                "in_active_hours": 8
            }
        }
        
        logger.info(f"Calling external API for absence request: {payload}")
        
        # HTTP POST дуудлага хийх
        response = requests.post(
            api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"External API success: {result}")
            
            # Response-аас absence_id авах оролдлого
            absence_id = None
            if isinstance(result, dict):
                # API response structure: {'result': {'absence_id': 342, ...}}
                absence_id = (result.get("result", {}).get("absence_id") or 
                             result.get("absence_id") or 
                             result.get("id") or 
                             result.get("data", {}).get("id"))
                logger.info(f"Extracted absence_id: {absence_id} from API response")
            
            return {
                "success": True,
                "data": result,
                "absence_id": absence_id,
                "message": "Absence request created successfully"
            }
        else:
            logger.error(f"External API error - Status: {response.status_code}, Response: {response.text}")
            return {
                "success": False,
                "error": f"API returned status {response.status_code}",
                "message": response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error("External API timeout")
        return {
            "success": False,
            "error": "API timeout",
            "message": "External API request timed out"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"External API request error: {str(e)}")
        return {
            "success": False,
            "error": "Request failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error calling external API: {str(e)}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }

async def call_approve_absence_api(absence_id, comment="Зөвшөөрсөн"):
    """External API руу absence approve дуудлага хийх"""
    try:
        api_url = "https://mcp-server-production-6219.up.railway.app/call-function"
        
        # API payload бэлтгэх
        payload = {
            "function": "approve_absence",
            "args": {
                "absence_id": absence_id,
                "comment": comment
            }
        }
        
        logger.info(f"Calling external API for absence approval: {payload}")
        
        # HTTP POST дуудлага хийх
        response = requests.post(
            api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"External API approval success: {result}")
            return {
                "success": True,
                "data": result,
                "message": "Absence approved successfully"
            }
        else:
            logger.error(f"External API approval error - Status: {response.status_code}, Response: {response.text}")
            return {
                "success": False,
                "error": f"API returned status {response.status_code}",
                "message": response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error("External API approval timeout")
        return {
            "success": False,
            "error": "API timeout",
            "message": "External API request timed out"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"External API approval request error: {str(e)}")
        return {
            "success": False,
            "error": "Request failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error calling external approval API: {str(e)}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }

async def call_reject_absence_api(absence_id, comment=""):
    """External API руу absence reject дуудлага хийх"""
    try:
        api_url = "https://mcp-server-production-6219.up.railway.app/call-function"
        
        # API payload бэлтгэх
        payload = {
            "function": "reject_absence",
            "args": {
                "absence_id": absence_id,
                "comment": comment
            }
        }
        
        logger.info(f"Calling external API for absence rejection: {payload}")
        
        # HTTP POST дуудлага хийх
        response = requests.post(
            api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"External API rejection success: {result}")
            return {
                "success": True,
                "data": result,
                "message": "Absence rejected successfully"
            }
        else:
            logger.error(f"External API rejection error - Status: {response.status_code}, Response: {response.text}")
            return {
                "success": False,
                "error": f"API returned status {response.status_code}",
                "message": response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error("External API rejection timeout")
        return {
            "success": False,
            "error": "API timeout",
            "message": "External API request timed out"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"External API rejection request error: {str(e)}")
        return {
            "success": False,
            "error": "Request failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error calling external rejection API: {str(e)}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }
    
async def send_teams_webhook_notification(requester_name):
    """Teams webhook руу зөвшөөрөлийн мэдэгдэл илгээх"""
    try:
        webhook_url = "https://prod-36.southeastasia.logic.azure.com:443/workflows/6dcb3cbe39124404a12b754720b25699/triggers/manual/paths/invoke?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=nhqRPaYSLixFlWOePwBHVlyWrbAv6OL7h0SNclMZS0U"
        
        # Teams webhook payload бэлтгэх
        payload = {
            "message": f"{requester_name} чөлөө авсан шүү, манайхаан."
        }
        
        logger.info(f"Sending Teams webhook notification for {requester_name}")
        
        # HTTP POST дуудлага хийх
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Teams webhook notification sent successfully for {requester_name}")
            return {
                "success": True,
                "message": "Teams notification sent successfully"
            }
        else:
            logger.error(f"Teams webhook error - Status: {response.status_code}, Response: {response.text}")
            return {
                "success": False,
                "error": f"Webhook returned status {response.status_code}",
                "message": response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error("Teams webhook timeout")
        return {
            "success": False,
            "error": "Webhook timeout",
            "message": "Teams webhook request timed out"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Teams webhook request error: {str(e)}")
        return {
            "success": False,
            "error": "Request failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error calling Teams webhook: {str(e)}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }

def save_leave_request(request_data):
    """Чөлөөний хүсэлтийг хадгалах"""
    try:
        request_id = request_data["request_id"]
        filename = f"{LEAVE_REQUESTS_DIR}/request_{request_id}.json"
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(request_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved leave request {request_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save leave request: {str(e)}")
        return False

def load_leave_request(request_id):
    """Чөлөөний хүсэлтийг унших"""
    try:
        filename = f"{LEAVE_REQUESTS_DIR}/request_{request_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load leave request {request_id}: {str(e)}")
        return None

def is_leave_request(text):
    """Мессеж нь чөлөөний хүсэлт эсэхийг шалгах"""
    leave_keywords = [
        'чөлөө', 'амралт', 'leave', 'vacation', 'holiday',
        'чөлөөний хүсэлт', 'амралтын хүсэлт', 'чөлөө авах',
        'амрах', 'чөлөөтэй байх', 'амралтанд явах'
    ]
    
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in leave_keywords)

def parse_leave_request(text, user_name):
    """ChatGPT-4 ашиглаж чөлөөний хүсэлтийн мэдээллийг ойлгох"""
    try:
        if not openai_client.api_key:
            logger.warning("OpenAI API key not configured, falling back to simple parsing")
            return parse_leave_request_simple(text, user_name)
        
        # Өнөөдрийн огноог AI-д өгөх
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        tomorrow = today + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        
        prompt = f"""
Та чөлөөний хүсэлт боловсруулах туслах юм. Доорх мессежээс database.Absence struct-д оруулах мэдээллийг гаргаж, JSON хэлбэрээр буцаа.

ӨНӨӨДРИЙН ОГНОО: {today_str} ({today.strftime("%A")})
МАРГААШИЙН ОГНОО: {tomorrow_str} ({tomorrow.strftime("%A")})

Хэрэглэгч: {user_name}
Мессеж: "{text}"

Database schema (Go struct):
type Absence struct {{
    StartDate     time.Time
    Reason        string
    EmployeeID    uint
    InActiveHours int
    Status        string
}}

Гаргах ёстой мэдээлэл:
- start_date: Эхлэх огноо (YYYY-MM-DD формат)
- end_date: Дуусах огноо (YYYY-MM-DD формат) 
- reason: Шалтгаан (string)
- employee_id: Ажилтны ID (засвар хийх шаардлагагүй, backend дээр тохируулна)
- inactive_hours: Идэвхгүй цагийн тоо (ЦААГААР тооцоолох)
- status: Төлөв (default: "pending")
- needs_clarification: Нэмэлт мэдээлэл хэрэгтэй эсэх (true/false)
- questions: Хэрэв needs_clarification true бол асуух асуултууд

ЧУХАЛ ДҮРЭМ:
- "МАРГААШ" = {tomorrow_str}
- "ӨНӨӨДӨР" = {today_str}
- "ХОЁР ӨДРИЙН ДАРАА" = {(today + timedelta(days=2)).strftime("%Y-%m-%d")}
- "ЭНЭ ДОЛОО ХОНОГ" = одоогийн долоо хоногт
- "ДАРААГИЙН ДОЛОО ХОНОГ" = дараагийн долоо хоногт

ЦАГИЙН ТООЦООЛОЛ:
- "1 ХОНОГ" = 8 цаг
- "0.5 ХОНОГ" эсвэл "ХАГАС ХОНОГ" = 4 цаг
- "2 ЦАГ" = 2 цаг
- "3 ЦАГ" = 3 цаг
- "4 ЦАГ" = 4 цаг
- "ӨГЛӨӨний ЦАГ" эсвэл "ӨГЛӨӨ" = 4 цаг
- "ҮДЭЭС ХОЙШ" эсвэл "ҮДИЙН ЦАГ" = 4 цаг

ОГНООНЫ ДҮРЭМ:
- Хэрэв inactive_hours < 8 (цагийн чөлөө) бол start_date = end_date (тэр өдөр л)
- Хэрэв inactive_hours >= 8 (хоногийн чөлөө) бол end_date = start_date + (хоногийн тоо - 1)
- Хэрэв огноо тодорхойгүй бол тодорхой болж асуух
- Хэрэв цаг/хоног тодорхойгүй бол 8 цаг (1 хоног) гэж үзэх
- Хэрэв шалтгаан байхгүй бол "Хувийн шаардлага" гэж үзэх
- Status үргэлж "pending" байна
- Хэрэв мэдээлэл дутуу бол needs_clarification = true болгож асуултууд нэмэх

ӨНӨӨДРИЙН ОГНОО ({today_str})-ийг үндэслэн тооцоол хийнэ үү!

JSON буцаа:
"""

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": f"Та чөлөөний хүсэлт боловсруулах туслах. Монгол хэл дээрх байгалийн хэлийг ойлгож, database.Absence struct-д тохирох бүтцлэгдсэн мэдээлэл гаргадаг. ӨНӨӨДРИЙН ОГНОО: {today_str}. 'Маргааш' гэсэн үг {tomorrow_str} гэсэн үг юм."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )
        
        ai_response = response.choices[0].message.content.strip()
        logger.info(f"AI response: {ai_response}")
        
        # JSON парсах оролдлого
        try:
            # JSON кодын хэсгийг олох
            import re
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                parsed_data = json.loads(json_str)
                
                # Default утгууд шалгах
                today = datetime.now()
                if not parsed_data.get('start_date'):
                    parsed_data['start_date'] = today.strftime("%Y-%m-%d")
                if not parsed_data.get('reason'):
                    parsed_data['reason'] = "Хувийн шаардлага"
                if not parsed_data.get('status'):
                    parsed_data['status'] = "pending"
                if not parsed_data.get('inactive_hours'):
                    # Default 1 хоног = 8 цаг
                    parsed_data['inactive_hours'] = 8
                
                # Хуучин системтэй нийцүүлэх
                parsed_data['requester_name'] = user_name
                
                # Хоногийн тоо зөв тооцоолох
                inactive_hours = parsed_data.get('inactive_hours', 8)
                if inactive_hours < 8:
                    # Цагийн чөлөө - 1 өдөр
                    parsed_data['days'] = 1
                else:
                    # Хоногийн чөлөө - цагаар хуваах
                    parsed_data['days'] = max(1, inactive_hours // 8)
                
                # End date тооцоолох
                if not parsed_data.get('end_date'):
                    start_date = datetime.strptime(parsed_data['start_date'], "%Y-%m-%d")
                    
                    if inactive_hours < 8:
                        # Цагийн чөлөө - тэр өдөр л
                        end_date = start_date
                    else:
                        # Хоногийн чөлөө - хоногийн тоогоор тооцоолох
                        end_date = start_date + timedelta(days=parsed_data['days'] - 1)
                    
                    parsed_data['end_date'] = end_date.strftime("%Y-%m-%d")
                
                return parsed_data
            else:
                logger.error("No JSON found in AI response")
                return parse_leave_request_simple(text, user_name)
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI JSON response: {e}")
            return parse_leave_request_simple(text, user_name)
            
    except Exception as e:
        logger.error(f"AI parsing error: {str(e)}")
        return parse_leave_request_simple(text, user_name)

def parse_leave_request_simple(text, user_name):
    """Энгийн regex ашиглах fallback функц"""
    
    # Өнөөдрийн огноо олох
    today = datetime.now()
    
    # Цаг ба хоногийн тоо олох
    text_lower = text.lower()
    
    # Цагийн тоо шалгах
    hours_match = re.search(r'(\d+)\s*(?:цаг|час|hour)', text_lower)
    
    # Хоногийн тоо шалгах
    days_match = re.search(r'(\d+)\s*(?:хоног|өдөр|day)', text_lower)
    
    # Хагас хоног шалгах
    half_day_patterns = ['хагас хоног', '0.5 хоног', 'хагас өдөр', 'өглөө', 'үдээс хойш', 'үдийн цаг']
    is_half_day = any(pattern in text_lower for pattern in half_day_patterns)
    
    # Цагийн тоо тодорхойлох
    if hours_match:
        inactive_hours = int(hours_match.group(1))
        days = max(1, inactive_hours // 8) if inactive_hours >= 8 else 1  # Хамгийн багадаа 1 өдөр
    elif is_half_day:
        inactive_hours = 4
        days = 1
    elif days_match:
        days = int(days_match.group(1))
        inactive_hours = days * 8
    else:
        # Default - 1 хоног
        days = 1
        inactive_hours = 8
    
    # Start date тодорхойлох
    if 'маргааш' in text_lower:
        start_date_obj = today + timedelta(days=1)
    elif 'өнөөдөр' in text_lower:
        start_date_obj = today
    elif 'хоёр өдрийн дараа' in text_lower:
        start_date_obj = today + timedelta(days=2)
    elif 'гурав өдрийн дараа' in text_lower or '3 өдрийн дараа' in text_lower:
        start_date_obj = today + timedelta(days=3)
    else:
        # Default - өнөөдөр
        start_date_obj = today
    
    start_date = start_date_obj.strftime("%Y-%m-%d")
    
    # End date тооцоолох - ЗӨВХӨН days-аар тооцоолох
    if inactive_hours < 8:
        # Цагийн чөлөө бол тэр өдөр л
        end_date_obj = start_date_obj
    else:
        # Хоногийн чөлөө - эхлэх өдрөөс хэдэн хоног нэмэх
        end_date_obj = start_date_obj + timedelta(days=days-1)
    
    end_date = end_date_obj.strftime("%Y-%m-%d")
    
    # Шалтгаан гаргах
    reason_keywords = ['учир', 'шалтгаан', 'because', 'reason', 'for']
    reason = "Хувийн шаардлага"
    
    for keyword in reason_keywords:
        if keyword in text.lower():
            parts = text.lower().split(keyword)
            if len(parts) > 1:
                reason = parts[1].strip()[:100]  # Эхний 100 тэмдэгт
                break
    
    return {
        "requester_name": user_name,
        "start_date": start_date,
        "end_date": end_date, 
        "days": days,
        "reason": reason,
        "inactive_hours": inactive_hours,
        "status": "pending",
        "needs_clarification": False,
        "questions": []
    }

async def handle_leave_request_message(context: TurnContext, text, user_id, user_name):
    """Чөлөөний хүсэлтийн мессежийг боловсруулах"""
    try:
        # Хүсэлт гаргагчийн мэдээлэл олох
        requester_info = None
        for user in list_all_users():
            if user["user_id"] == user_id:
                requester_info = user
                break
        
        if not requester_info:
            await context.send_activity("❌ Таны мэдээлэл олдсонгүй. Эхлээд bot-тай чатлана уу.")
            return
        
        # Мессежээс мэдээлэл гаргах
        parsed_data = parse_leave_request(text, user_name or requester_info.get("user_name", "Unknown"))
        
        # Хүсэлтийн ID үүсгэх
        request_id = str(uuid.uuid4())
        
        # Хүсэлтийн мэдээлэл бэлтгэх
        request_data = {
            "request_id": request_id,
            "requester_email": requester_info.get("email"),
            "requester_name": parsed_data["requester_name"],
            "requester_user_id": user_id,
            "start_date": parsed_data["start_date"],
            "end_date": parsed_data["end_date"],
            "days": parsed_data["days"],
            "reason": parsed_data["reason"],
            "inactive_hours": parsed_data.get("inactive_hours", parsed_data["days"] * 8),
            "status": parsed_data.get("status", "pending"),
            "original_message": text,
            "created_at": datetime.now().isoformat(),
            "approver_email": APPROVER_EMAIL,
            "approver_user_id": APPROVER_USER_ID
        }
        
        # Хүсэлт хадгалах
        save_leave_request(request_data)
        
        # Хүсэлт гаргагчид хариулах
        await context.send_activity(f"✅ Чөлөөний хүсэлт хүлээн авлаа!\n📅 {parsed_data['start_date']} - {parsed_data['end_date']} ({parsed_data['days']} хоног)\n💭 {parsed_data['reason']}\n⏳ Зөвшөөрөлийн хүлээлгэд байна...{api_status_msg}")
        
        # Bayarmunkh руу adaptive card илгээх
        approval_card = create_approval_card(request_data)
        approver_conversation = load_conversation_reference(APPROVER_USER_ID)
        
        # External API руу absence request үүсгэх
        api_result = await call_external_absence_api(request_data)
        api_status_msg = ""
        if api_result["success"]:
            api_status_msg = "\n✅ Системд амжилттай бүртгэгдлээ"
            # Absence ID хадгалах
            if api_result.get("absence_id"):
                request_data["absence_id"] = api_result["absence_id"]
                save_leave_request(request_data)  # Absence ID-тай дахин хадгалах
        else:
            api_status_msg = f"\n⚠️ Системд бүртгэхэд алдаа: {api_result.get('message', 'Unknown error')}"
        
        if approver_conversation:
            async def send_approval_card(ctx: TurnContext):
                adaptive_card_attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=approval_card
                )
                # Planner tasks мэдээлэл авах
                planner_info = ""
                if request_data.get("requester_email"):
                    try:
                        planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                    except Exception as e:
                        logger.error(f"Failed to get planner tasks for manager notification: {str(e)}")
                
                message = MessageFactory.attachment(adaptive_card_attachment)
                message.text = f"📩 Шинэ чөлөөний хүсэлт: {request_data['requester_name']}\n💬 Анхны мессеж: \"{text}\"{api_status_msg}{planner_info}"
                await ctx.send_activity(message)
            
            await ADAPTER.continue_conversation(
                approver_conversation,
                send_approval_card,
                app_id
            )
            logger.info(f"Leave request {request_id} sent to approver")
        else:
            logger.warning(f"Approver conversation reference not found for leave request {request_id}")
            # Approver-тай холбогдож чадахгүй байгаа тул хүсэлт хадгалагдсан гэдгийг мэдэгдэх
            await context.send_activity("⚠️ Зөвшөөрөгч bot-тай хараахан холбогдоогүй байна. Хүсэлт хадгалагдсан боловч зөвшөөрөгчтэй шууд холбогдоно уу.")
        
        logger.info(f"Leave request {request_id} created from message by {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling leave request message: {str(e)}")
        await context.send_activity(f"❌ Чөлөөний хүсэлт боловсруулахад алдаа гарлаа: {str(e)}")

async def forward_message_to_admin(text, user_name, user_id):
    """Ердийн мессежийг админд adaptive card-тай дамжуулах"""
    try:        
        approver_conversation = load_conversation_reference(APPROVER_USER_ID)
        
        if approver_conversation:
            # Энгийн мессежээс чөлөөний хүсэлт үүсгэх
            parsed_data = parse_leave_request(text, user_name)
            
            # Хэрэв AI нь нэмэлт мэдээлэл хэрэгтэй гэж үзвэл
            if parsed_data.get('needs_clarification', False):
                questions = parsed_data.get('questions', [])
                if questions:
                    # Хэрэглэгчээс нэмэлт мэдээлэл асуух
                    question_text = "🤔 Чөлөөний хүсэлтийг боловсруулахын тулд нэмэлт мэдээлэл хэрэгтэй байна:\n\n"
                    for i, question in enumerate(questions, 1):
                        question_text += f"{i}. {question}\n"
                    question_text += "\nДахин мессеж илгээж дэлгэрэнгүй мэдээлэл өгнө үү."
                    
                    # Хэрэглэгчээс асуулт асуух логик нэмэх хэрэгтэй
                    # Одоогоор зөвхөн админд мэдэгдэх
                    async def notify_admin_clarification(ctx: TurnContext):
                        await ctx.send_activity(f"❓ {user_name} нэмэлт мэдээлэл хэрэгтэй:\n💬 Анхны мессеж: \"{text}\"\n🤔 Асуултууд: {', '.join(questions)}")
                    
                    await ADAPTER.continue_conversation(
                        approver_conversation,
                        notify_admin_clarification,
                        app_id
                    )
                    logger.info(f"Clarification needed message sent to admin from {user_id}")
                    return
            
            request_id = str(uuid.uuid4())
            
            # Хүсэлт гаргагчийн мэдээлэл олох
            requester_info = None
            all_users = list_all_users()
            
            for user in all_users:
                if user["user_id"] == user_id:
                    requester_info = user
                    break
            
            # Хүсэлтийн мэдээлэл бэлтгэх
            request_data = {
                "request_id": request_id,
                "requester_email": requester_info.get("email") if requester_info else "unknown@fibo.cloud",
                "requester_name": user_name,
                "requester_user_id": user_id,
                "start_date": parsed_data["start_date"],
                "end_date": parsed_data.get("end_date"),
                "days": parsed_data["days"],
                "reason": parsed_data["reason"],
                "inactive_hours": parsed_data.get("inactive_hours", parsed_data["days"] * 8),
                "status": parsed_data.get("status", "pending"),
                "original_message": text,
                "created_at": datetime.now().isoformat(),
                "approver_email": APPROVER_EMAIL,
                "approver_user_id": APPROVER_USER_ID
            }
            
            # Хүсэлт хадгалах
            save_leave_request(request_data)
            
            # External API руу absence request үүсгэх
            api_result = await call_external_absence_api(request_data)
            api_status_msg = ""
            if api_result["success"]:
                api_status_msg = "\n✅ Системд амжилттай бүртгэгдлээ"
                # Absence ID хадгалах
                if api_result.get("absence_id"):
                    request_data["absence_id"] = api_result["absence_id"]
                    save_leave_request(request_data)  # Absence ID-тай дахин хадгалах
            else:
                api_status_msg = f"\n⚠️ Системд бүртгэхэд алдаа: {api_result.get('message', 'Unknown error')}"
            
            # Adaptive card үүсгэх
            approval_card = create_approval_card(request_data)
            
            async def notify_admin_with_card(ctx: TurnContext):
                adaptive_card_attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=approval_card
                )
                # Planner tasks мэдээлэл авах
                planner_info = ""
                if request_data.get("requester_email"):
                    try:
                        planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                    except Exception as e:
                        logger.error(f"Failed to get planner tasks for admin notification: {str(e)}")
                
                message = MessageFactory.attachment(adaptive_card_attachment)
                message.text = f"📨 Шинэ мессеж: {user_name}\n💬 Анхны мессеж: \"{text}\"\n🤖 AI ойлголт: {parsed_data.get('days')} хоног, {parsed_data.get('reason')}{api_status_msg}{planner_info}"
                await ctx.send_activity(message)
            
            await ADAPTER.continue_conversation(
                approver_conversation,
                notify_admin_with_card,
                app_id
            )
            logger.info(f"Message with adaptive card forwarded to admin from {user_id}")
        else:
            logger.warning(f"Approver conversation reference not found. Approver needs to message the bot first.")
            # Approver conversation байхгүй тул мессежийг log-д хадгална
            logger.info(f"Pending message for admin: {user_name} said: {text}")
    except Exception as e:
        logger.error(f"Error forwarding message to admin: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

def save_conversation_reference(activity):
    """Хэрэглэгчийн conversation reference болон нэмэлт мэдээллийг хадгалах функц"""
    try:
        reference = TurnContext.get_conversation_reference(activity)
        user_id = activity.from_property.id if activity.from_property else "unknown"
        conversation_id = activity.conversation.id if activity.conversation else "unknown"
        
        # Хэрэглэгчийн нэмэлт мэдээлэл цуглуулах
        user_info = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "user_name": getattr(activity.from_property, 'name', None) if activity.from_property else None,
            "email": None,
            "last_activity": activity.timestamp.isoformat() if activity.timestamp else None,
            "channel_id": activity.channel_id,
            "service_url": activity.service_url,
            "conversation_reference": reference.serialize(),
            "conversation_details": {
                "conversation_id": activity.conversation.id if activity.conversation else None,
                "conversation_type": getattr(activity.conversation, 'conversation_type', None) if activity.conversation else None,
                "tenant_id": getattr(activity.conversation, 'tenant_id', None) if activity.conversation else None,
                "is_group": getattr(activity.conversation, 'is_group', None) if activity.conversation else None,
                "name": getattr(activity.conversation, 'name', None) if activity.conversation else None
            }
        }
        
        # Мэйл хаяг олох оролдлого (Teams-ээс ихэвчлэн name дотор байдаг)
        if activity.from_property and activity.from_property.name:
            name = activity.from_property.name
            # Мэйл хаяг шиг харагдах эсэхийг шалгах
            if "@" in name and "." in name:
                user_info["email"] = name
                # User name-г мэйлээс салгаж авах
                if " <" in name:
                    user_info["user_name"] = name.split(" <")[0]
                    user_info["email"] = name.split(" <")[1].rstrip(">")
                elif "<" in name and ">" in name:
                    user_info["email"] = name.split("<")[1].split(">")[0]
            else:
                # Мэйл хаяг байхгүй бол display name-аас үүсгэх
                # "Tuvshinjargal Enkhtaivan" -> "tuvshinjargal@fibo.cloud"
                user_info["user_name"] = name
                if name and name.strip():
                    # Эхний үгийг авч жижиг үсэг болгох
                    first_name = name.strip().split()[0].lower()
                    # Тусгай тэмдэгтүүдийг арилгах
                    first_name = re.sub(r'[^a-zA-Z0-9]', '', first_name)
                    user_info["email"] = f"{first_name}@fibo.cloud"
        
        # Additional Azure AD properties шалгах
        if hasattr(activity.from_property, 'aad_object_id'):
            user_info["aad_object_id"] = activity.from_property.aad_object_id
        
        # Хэрэглэгчийн ID-ээр файлын нэр үүсгэх (special characters-ээс зайлсхийх)
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(user_info, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved conversation reference for user {user_id} (email: {user_info.get('email', 'N/A')}) to {filename}")
        return filename
    except Exception as e:
        logger.error(f"Failed to save conversation reference: {str(e)}")
        return None

def load_conversation_reference(user_id):
    """Хэрэглэгчийн conversation reference-г унших функц"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            logger.error(f"Conversation file not found for user {user_id}")
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            user_info = json.load(f)
        
        # Хуучин формат шалгах (зөвхөн conversation_reference байх)
        if "conversation_reference" in user_info:
            return ConversationReference().deserialize(user_info["conversation_reference"])
        else:
            # Хуучин формат байна гэж үзэж
            return ConversationReference().deserialize(user_info)
    except Exception as e:
        logger.error(f"Failed to load conversation reference for user {user_id}: {str(e)}")
        return None

def load_user_info(user_id):
    """Хэрэглэгчийн бүрэн мэдээллийг унших функц"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load user info for {user_id}: {str(e)}")
        return None

def list_all_users():
    """Хадгалагдсан бүх хэрэглэгчийн дэлгэрэнгүй мэдээлэл гаргах"""
    try:
        users = []
        for filename in os.listdir(CONVERSATION_DIR):
            if filename.startswith("user_") and filename.endswith(".json"):
                user_id = filename[5:-5].replace("_", ":")  # user_ prefix болон .json suffix арилгах
                user_info = load_user_info(user_id)
                if user_info:
                    # Хуучин формат шалгах
                    if "user_id" in user_info:
                        users.append({
                            "user_id": user_info.get("user_id", user_id),
                            "email": user_info.get("email"),
                            "user_name": user_info.get("user_name"),
                            "last_activity": user_info.get("last_activity"),
                            "channel_id": user_info.get("channel_id"),
                            "conversation_id": user_info.get("conversation_id"),
                            "conversation_type": user_info.get("conversation_details", {}).get("conversation_type"),
                            "tenant_id": user_info.get("conversation_details", {}).get("tenant_id"),
                            "is_group": user_info.get("conversation_details", {}).get("is_group"),
                            "conversation_name": user_info.get("conversation_details", {}).get("name")
                        })
                    else:
                        # Хуучин формат - зөвхөн user_id нэмэх
                        users.append({
                            "user_id": user_id,
                            "email": None,
                            "user_name": None,
                            "last_activity": None,
                            "channel_id": None,
                            "conversation_id": None,
                            "conversation_type": None,
                            "tenant_id": None,
                            "is_group": None,
                            "conversation_name": None
                        })
                else:
                    users.append({
                        "user_id": user_id,
                        "email": None,
                        "user_name": None,
                        "last_activity": None,
                        "channel_id": None,
                        "conversation_id": None,
                        "conversation_type": None,
                        "tenant_id": None,
                        "is_group": None,
                        "conversation_name": None
                    })
        return users
    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}")
        return []

def find_user_by_conversation_id(conversation_id):
    """Conversation ID-аар хэрэглэгч олох"""
    for user in list_all_users():
        if user.get("conversation_id") == conversation_id:
            return user
    return None

def save_user_absence_id(user_id, absence_id):
    """Хэрэглэгчийн файлд absence_id хадгалах"""
    try:
        user_info = load_user_info(user_id)
        if user_info:
            user_info["current_absence_id"] = absence_id
            user_info["absence_updated_at"] = datetime.now().isoformat()
            
            safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
            filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(user_info, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved absence_id {absence_id} for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to save absence_id for user {user_id}: {str(e)}")
        return False

def get_user_absence_id(user_id):
    """Хэрэглэгчийн absence_id авах"""
    try:
        user_info = load_user_info(user_id)
        if user_info:
            return user_info.get("current_absence_id")
    except Exception as e:
        logger.error(f"Failed to get absence_id for user {user_id}: {str(e)}")
    return None

def clear_user_absence_id(user_id):
    """Хэрэглэгчийн absence_id устгах"""
    try:
        user_info = load_user_info(user_id)
        if user_info:
            user_info.pop("current_absence_id", None)
            user_info.pop("absence_updated_at", None)
            
            safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
            filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(user_info, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Cleared absence_id for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to clear absence_id for user {user_id}: {str(e)}")
        return False

@app.route("/", methods=["GET"])
def health_check():
    pending_confirmations = len([f for f in os.listdir(PENDING_CONFIRMATIONS_DIR) if f.startswith("pending_") and not f.startswith("pending_rejection_")]) if os.path.exists(PENDING_CONFIRMATIONS_DIR) else 0
    pending_rejections = len([f for f in os.listdir(PENDING_CONFIRMATIONS_DIR) if f.startswith("pending_rejection_")]) if os.path.exists(PENDING_CONFIRMATIONS_DIR) else 0
    
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server is running",
        "endpoints": ["/api/messages", "/proactive-message", "/users", "/broadcast", "/leave-request", "/approval-callback", "/send-by-conversation"],
        "app_id_configured": bool(os.getenv("MICROSOFT_APP_ID")),
        "stored_users": len(list_all_users()),
        "pending_confirmations": pending_confirmations,
        "pending_rejections": pending_rejections
    })

@app.route("/users", methods=["GET"])
def get_users():
    """Хадгалагдсан хэрэглэгчдийн жагсаалт"""
    users = list_all_users()
    return jsonify({"users": users, "count": len(users)})

@app.route("/leave-request", methods=["POST"])
def submit_leave_request():
    """Чөлөөний хүсэлт гаргах"""
    try:
        data = request.json
        requester_email = data.get("requester_email")
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        days = data.get("days")
        reason = data.get("reason", "Хувийн шаардлага")

        if not all([requester_email, start_date, end_date, days]):
            return jsonify({"error": "Missing required fields: requester_email, start_date, end_date, days"}), 400

        # Хүсэлт гаргагчийн мэдээлэл олох
        requester_info = None
        for user in list_all_users():
            if user["email"] == requester_email:
                requester_info = user
                break

        if not requester_info:
            return jsonify({"error": f"User with email {requester_email} not found"}), 404

        # Хүсэлтийн мэдээлэл бэлтгэх
        request_id = str(uuid.uuid4())
        request_data = {
            "request_id": request_id,
            "requester_email": requester_email,
            "requester_name": requester_info.get("user_name", requester_email),
            "requester_user_id": requester_info["user_id"],
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "reason": reason,
            "inactive_hours": days * 8,  # 8 цагийн ажлын өдөр
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "approver_email": APPROVER_EMAIL,
            "approver_user_id": APPROVER_USER_ID
        }

        # Хүсэлт хадгалах
        if not save_leave_request(request_data):
            return jsonify({"error": "Failed to save leave request"}), 500

        # External API руу absence request үүсгэх
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        api_result = loop.run_until_complete(call_external_absence_api(request_data))
        
        api_status_msg = ""
        if api_result["success"]:
            api_status_msg = "\n✅ Системд амжилттай бүртгэгдлээ"
            # Absence ID хадгалах
            if api_result.get("absence_id"):
                request_data["absence_id"] = api_result["absence_id"]
                save_leave_request(request_data)  # Absence ID-тай дахин хадгалах
        else:
            api_status_msg = f"\n⚠️ Системд бүртгэхэд алдаа: {api_result.get('message', 'Unknown error')}"

        # Approval card үүсгэх
        approval_card = create_approval_card(request_data)

        # Approver руу adaptive card илгээх
        approver_conversation = load_conversation_reference(APPROVER_USER_ID)
        if not approver_conversation:
            return jsonify({"error": "Approver conversation reference not found"}), 404

        async def send_approval_card(context: TurnContext):
            adaptive_card_attachment = Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=approval_card
            )
            # Planner tasks мэдээлэл авах
            planner_info = ""
            if request_data.get("requester_email"):
                try:
                    planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                except Exception as e:
                    logger.error(f"Failed to get planner tasks for REST API request: {str(e)}")
            
            message = MessageFactory.attachment(adaptive_card_attachment)
            message.text = f"📩 Шинэ чөлөөний хүсэлт: {request_data['requester_name']}\n💬 REST API-аас илгээгдсэн{api_status_msg}{planner_info}"
            await context.send_activity(message)

        asyncio.run(
            ADAPTER.continue_conversation(
                approver_conversation,
                send_approval_card,
                app_id
            )
        )

        # Хүсэлт гаргагч руу баталгаажуулах мессеж илгээх
        requester_conversation = load_conversation_reference(requester_info["user_id"])
        if requester_conversation:
            async def send_confirmation(context: TurnContext):
                await context.send_activity(f"✅ Таны чөлөөний хүсэлт амжилттай илгээгдлээ!\n📅 {start_date} - {end_date} ({days} хоног)\n⏳ Зөвшөөрөлийн хүлээлгэд байна...")

            asyncio.run(
                ADAPTER.continue_conversation(
                    requester_conversation,
                    send_confirmation,
                    app_id
                )
            )

        logger.info(f"Leave request {request_id} submitted by {requester_email}")
        return jsonify({
            "status": "success",
            "request_id": request_id,
            "message": "Leave request submitted successfully"
        }), 200

    except Exception as e:
        logger.error(f"Leave request error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages", methods=["POST"])
def process_messages():
    try:
        logger.info("Received message request")
        if not request.is_json:
            logger.error("Request is not JSON")
            return jsonify({"error": "Content-Type must be application/json"}), 400

        body = request.get_json()
        logger.info(f"Request body: {body}")

        if not body:
            logger.error("Empty request body")
            return jsonify({"error": "Request body is required"}), 400

        try:
            activity = Activity().deserialize(body)
            logger.info(f"Activity type: {activity.type}, text: {activity.text}")
        except Exception as e:
            logger.error(f"Failed to deserialize activity: {str(e)}")
            return jsonify({"error": f"Invalid activity format: {str(e)}"}), 400

        # Хэрэглэгчийн conversation reference хадгалах
        save_conversation_reference(activity)

        async def logic(context: TurnContext):
            try:
                if activity.type == "message":
                    # Adaptive card action шалгах
                    if activity.value:
                        # Adaptive card submit action
                        action_data = activity.value
                        await handle_adaptive_card_action(context, action_data)
                    else:
                        # Ердийн мессеж
                        user_text = activity.text or "No text provided"
                        user_id = activity.from_property.id if activity.from_property else "unknown"
                        user_name = getattr(activity.from_property, 'name', None) if activity.from_property else "Unknown User"
                        logger.info(f"Processing message from user {user_id}: {user_text}")
                        
                        # Зөвхөн Bayarmunkh биш хэрэглэгчдийн мессежийг боловсруулах
                        if user_id != APPROVER_USER_ID:
                            # Хэрэв хэрэглэгчтэй pending confirmation байвал
                            pending_confirmation = load_pending_confirmation(user_id)
                            
                            if pending_confirmation:
                                # Баталгаажуулалтын хариу шалгах
                                confirmation_response = is_confirmation_response(user_text)
                                
                                if confirmation_response == "approve":
                                    # Зөвшөөрсөн - менежер руу илгээх
                                    request_data = pending_confirmation["request_data"]
                                    
                                    # Баталгаажуулалт устгах
                                    delete_pending_confirmation(user_id)
                                    
                                    # Хүсэлт хадгалах
                                    save_leave_request(request_data)
                                    
                                    # External API руу absence request үүсгэх
                                    api_result = await call_external_absence_api(request_data)
                                    api_status_msg = ""
                                    if api_result["success"]:
                                        api_status_msg = "\n✅ Системд амжилттай бүртгэгдлээ"
                                        # Absence ID хадгалах
                                        if api_result.get("absence_id"):
                                            request_data["absence_id"] = api_result["absence_id"]
                                            save_leave_request(request_data)  # Absence ID-тай дахин хадгалах
                                            
                                            # Хэрэглэгчийн файлд absence_id хадгалах
                                            save_user_absence_id(user_id, api_result["absence_id"])
                                    else:
                                        api_status_msg = f"\n⚠️ Системд бүртгэхэд алдаа: {api_result.get('message', 'Unknown error')}"
                                    
                                    await context.send_activity(f"✅ Чөлөөний хүсэлт баталгаажсан!\n📤 Менежер руу илгээгдэж байна...{api_status_msg}")
                                    
                                    # Менежер руу илгээх
                                    await send_approved_request_to_manager(request_data, user_text)
                                    
                                elif confirmation_response == "reject":
                                    # Татгалзсан - дахин оруулахыг хүсэх
                                    delete_pending_confirmation(user_id)
                                    await context.send_activity("❌ Баталгаажуулалт цуцлагдлаа.\n\n🔄 Чөлөөний хүсэлтээ дахин илгээнэ үү. Дэлгэрэнгүй мэдээлэлтэй бичнэ үү.")
                                    
                                else:
                                    # Ойлгомжгүй хариу
                                    await context.send_activity('🤔 Ойлгосонгүй. "Тийм" эсвэл "Үгүй" гэж хариулна уу.\n\n• **"Тийм"** - Менежер руу илгээх\n• **"Үгүй"** - Засварлах')
                                
                                return
                            
                            # Шинэ хүсэлт - AI ашиглаж parse хийх
                            parsed_data = parse_leave_request(user_text, user_name)
                            
                            # Хэрэв AI нь нэмэлт мэдээлэл хэрэгтэй гэж үзвэл
                            if parsed_data.get('needs_clarification', False):
                                questions = parsed_data.get('questions', [])
                                if questions:
                                    # Хэрэглэгчээс нэмэлт мэдээлэл асуух
                                    question_text = "🤔 Чөлөөний хүсэлтийг боловсруулахын тулд нэмэлт мэдээлэл хэрэгтэй байна:\n\n"
                                    for i, question in enumerate(questions, 1):
                                        question_text += f"{i}. {question}\n"
                                    question_text += "\nДахин мессеж илгээж дэлгэрэнгүй мэдээлэл өгнө үү."
                                    
                                    await context.send_activity(question_text)
                                    logger.info(f"Asked clarification questions to user {user_id}")
                                    return
                            
                            # Мэдээлэл хангалттай - баталгаажуулалт асуух
                            # Request data бэлтгэх
                            request_id = str(uuid.uuid4())
                            
                            # Хэрэглэгчийн мэдээлэл олох
                            requester_info = None
                            all_users = list_all_users()
                            for user in all_users:
                                if user["user_id"] == user_id:
                                    requester_info = user
                                    break
                            
                            request_data = {
                                "request_id": request_id,
                                "requester_email": requester_info.get("email") if requester_info else "unknown@fibo.cloud",
                                "requester_name": user_name,
                                "requester_user_id": user_id,
                                "start_date": parsed_data["start_date"],
                                "end_date": parsed_data.get("end_date"),
                                "days": parsed_data["days"],
                                "reason": parsed_data["reason"],
                                "inactive_hours": parsed_data.get("inactive_hours", parsed_data["days"] * 8),
                                "status": parsed_data.get("status", "pending"),
                                "original_message": user_text,
                                "created_at": datetime.now().isoformat(),
                                "approver_email": APPROVER_EMAIL,
                                "approver_user_id": APPROVER_USER_ID
                            }
                            
                            # Pending confirmation хадгалах
                            save_pending_confirmation(user_id, request_data)
                            
                            # Баталгаажуулалт асуух
                            confirmation_message = create_confirmation_message(parsed_data, requester_info.get("email"))
                            await context.send_activity(confirmation_message)
                            
                            logger.info(f"Asked for confirmation from user {user_id}")
                            
                        else:
                            # Bayarmunkh өөрийн мессеж - pending rejection шалгах
                            pending_rejection = load_pending_rejection(user_id)
                            
                            if pending_rejection:
                                # Manager татгалзах шалтгаан илгээсэн
                                rejection_reason = user_text.strip()
                                request_data = pending_rejection["request_data"]
                                
                                # Pending rejection устгах
                                delete_pending_rejection(user_id)
                                
                                # Request data шинэчлэх
                                request_data["status"] = "rejected"
                                request_data["rejected_at"] = datetime.now().isoformat()
                                request_data["rejected_by"] = user_id
                                request_data["rejection_reason"] = rejection_reason
                                
                                # External API руу rejection дуудлага хийх
                                rejection_api_result = None
                                absence_id = request_data.get("absence_id") or get_user_absence_id(request_data["requester_user_id"])
                                
                                if absence_id:
                                    rejection_api_result = await call_reject_absence_api(
                                        absence_id, 
                                        rejection_reason
                                    )
                                    if rejection_api_result["success"]:
                                        logger.info(f"External API rejection successful for absence_id: {absence_id}")
                                    else:
                                        logger.error(f"External API rejection failed: {rejection_api_result.get('message', 'Unknown error')}")
                                else:
                                    logger.warning(f"No absence_id found for request {request_data['request_id']} or user {request_data['requester_user_id']}, skipping external rejection")
                                
                                # Хүсэлт хадгалах
                                save_leave_request(request_data)
                                
                                # Хэрэглэгчийн absence_id устгах (татгалзагдсан тул)
                                clear_user_absence_id(request_data["requester_user_id"])
                                
                                # Manager-д баталгаажуулах
                                api_status_msg = ""
                                if rejection_api_result:
                                    if rejection_api_result["success"]:
                                        api_status_msg = "\n✅ Системд автоматаар татгалзагдлаа"
                                    else:
                                        api_status_msg = f"\n⚠️ Системд татгалзахад алдаа: {rejection_api_result.get('message', 'Unknown error')}"
                                
                                await context.send_activity(f"✅ Чөлөөний хүсэлт татгалзагдлаа!\n📝 Хүсэлт: {request_data['requester_name']} - {request_data['start_date']} ({request_data['days']} хоног)\n💬 Татгалзах шалтгаан: \"{rejection_reason}\"\n📤 Хүсэлт гаргагчид мэдэгдэж байна...{api_status_msg}")
                                
                                # Хүсэлт гаргагч руу мэдэгдэх
                                requester_conversation = load_conversation_reference(request_data["requester_user_id"])
                                if requester_conversation:
                                    async def notify_rejection(ctx: TurnContext):
                                        await ctx.send_activity(f"❌ Таны чөлөөний хүсэлт татгалзагдлаа\n📅 {request_data['start_date']} - {request_data['end_date']} ({request_data['days']} хоног)\n💬 Татгалзах шалтгаан: \"{rejection_reason}\"\n\n🔄 Хэрэв шинэ хүсэлт гаргах бол дэлгэрэнгүй мэдээлэлтэй бичнэ үү.")

                                    await ADAPTER.continue_conversation(
                                        requester_conversation,
                                        notify_rejection,
                                        app_id
                                    )
                                
                                logger.info(f"Leave request {request_data['request_id']} rejected by {user_id} with reason: {rejection_reason}")
                            else:
                                # Ердийн мессеж - зөвхөн echo хариу
                                await context.send_activity(f"Таны мессежийг хүлээн авлаа: {user_text}")
                                logger.info(f"Skipping forwarding message to admin from approver himself: {user_id}")
                else:
                    logger.info(f"Non-message activity type: {activity.type}")
            except Exception as e:
                logger.error(f"Error in logic function: {str(e)}")
                await context.send_activity(f"Серверийн алдаа: {str(e)}")

        try:
            auth_header = request.headers.get('Authorization', '')
            logger.info(f"Auth header present: {bool(auth_header)}")
            asyncio.run(ADAPTER.process_activity(activity, auth_header, logic))
            logger.info("Message processed successfully")
            return jsonify({"status": "success"}), 200
        except Exception as e:
            logger.error(f"Adapter processing error: {str(e)}")
            return jsonify({"error": f"Bot framework error: {str(e)}"}), 500

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

async def handle_adaptive_card_action(context: TurnContext, action_data):
    """Adaptive card action-уудыг handle хийх"""
    try:
        action = action_data.get("action")
        request_id = action_data.get("request_id")
        
        if not action or not request_id:
            await context.send_activity("❌ Алдаатай хүсэлт")
            return

        # Leave request мэдээлэл унших
        request_data = load_leave_request(request_id)
        if not request_data:
            await context.send_activity("❌ Хүсэлт олдсонгүй")
            return

        # Disabled card үүсгэх
        def create_disabled_card(action_type):
            """Товчнууд идэвхгүй болсон card үүсгэх"""
            if action_type == "approve":
                status_text = "✅ ЗӨВШӨӨРӨГДСӨН"
                status_color = "good"
            else:
                status_text = "❌ ТАТГАЛЗАГДСАН"
                status_color = "attention"
            
            card = {
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "🏖️ Чөлөөний хүсэлт",
                        "weight": "bolder",
                        "size": "large",
                        "color": "accent"
                    },
                    {
                        "type": "TextBlock",
                        "text": status_text,
                        "weight": "bolder",
                        "color": status_color,
                        "size": "medium"
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            {
                                "title": "Хүсэлт гаргагч:",
                                "value": request_data.get("requester_name", "N/A")
                            },
                            {
                                "title": "Эхлэх өдөр:",
                                "value": request_data.get("start_date", "N/A")
                            },
                            {
                                "title": "Дуусах өдөр:",
                                "value": request_data.get("end_date", "N/A")
                            },
                            {
                                "title": "Хоногийн тоо:",
                                "value": str(request_data.get("days", "N/A"))
                            },
                            {
                                "title": "Цагийн тоо:",
                                "value": f"{request_data.get('inactive_hours', 'N/A')} цаг"
                            },
                            {
                                "title": "Шалтгаан:",
                                "value": request_data.get("reason", "Тодорхойгүй")
                            },
                            {
                                "title": "Боловсруулсан:",
                                "value": datetime.now().strftime("%Y-%m-%d %H:%M")
                            }
                        ]
                    }
                ],
                "actions": [
                    {
                        "type": "Action.Submit",
                        "title": "✅ Зөвшөөрөх",
                        "data": {
                            "action": "approve",
                            "request_id": request_data.get("request_id")
                        },
                        "style": "positive",
                        "isEnabled": False
                    },
                    {
                        "type": "Action.Submit", 
                        "title": "❌ Татгалзах",
                        "data": {
                            "action": "reject",
                            "request_id": request_data.get("request_id")
                        },
                        "style": "destructive",
                        "isEnabled": False
                    }
                ]
            }
            return card

        # Approval status шинэчлэх
        if action == "approve":
            request_data["status"] = "approved"
            request_data["approved_at"] = datetime.now().isoformat()
            request_data["approved_by"] = context.activity.from_property.id
            
            # External API руу approval дуудлага хийх
            approval_api_result = None
            if request_data.get("absence_id"):
                approval_api_result = await call_approve_absence_api(
                    request_data["absence_id"], 
                    "Зөвшөөрсөн"
                )
                if approval_api_result["success"]:
                    logger.info(f"External API approval successful for absence_id: {request_data['absence_id']}")
                else:
                    logger.error(f"External API approval failed: {approval_api_result.get('message', 'Unknown error')}")
            else:
                logger.warning(f"No absence_id found for request {request_id}, skipping external approval")
            
            # Хүсэлт хадгалах
            save_leave_request(request_data)
            
            # Teams webhook руу мэдэгдэл илгээх
            webhook_result = await send_teams_webhook_notification(request_data["requester_name"])
            webhook_status_msg = ""
            if webhook_result["success"]:
                webhook_status_msg = "\n📢 Teams-д мэдэгдэл илгээгдлээ"
            else:
                webhook_status_msg = f"\n⚠️ Teams мэдэгдэлд алдаа: {webhook_result.get('message', 'Unknown error')}"
            
            # Disabled card илгээх
            disabled_card = create_disabled_card("approve")
            adaptive_card_attachment = Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=disabled_card
            )
            disabled_message = MessageFactory.attachment(adaptive_card_attachment)
            await context.send_activity(disabled_message)
            
            # Хүсэлт гаргагч руу мэдэгдэх
            requester_conversation = load_conversation_reference(request_data["requester_user_id"])
            if requester_conversation:
                async def notify_approval(ctx: TurnContext):
                    approval_status_msg = ""
                    if approval_api_result:
                        if approval_api_result["success"]:
                            approval_status_msg = "\n✅ PMT дээр орлоо."
                        else:
                            approval_status_msg = f"\n⚠️ Системд зөвшөөрөхэд алдаа: {approval_api_result.get('message', 'Unknown error')}"
                    
                    await ctx.send_activity(f"🎉 Таны чөлөөний хүсэлт зөвшөөрөгдлөө!\n📅 {request_data['start_date']} - {request_data['end_date']} ({request_data['days']} хоног)\n✨ Сайхан амраарай!{approval_status_msg}{webhook_status_msg}")

                await ADAPTER.continue_conversation(
                    requester_conversation,
                    notify_approval,
                    app_id
                )
            
        elif action == "reject":
            # Manager-ээс татгалзах шалтгаан асуух
            manager_user_id = context.activity.from_property.id
            save_pending_rejection(manager_user_id, request_data)
            
            # Manager-д шалтгаан асуух
            await context.send_activity(f"❓ Татгалзах шалтгааныг бичнэ үү:\n\n📝 Хүсэлт: {request_data['requester_name']} - {request_data['start_date']} ({request_data['days']} хоног)\n💭 Шалтгаан: {request_data['reason']}\n\n✍️ Татгалзах шалтгааныг дараагийн мессежээр илгээнэ үү...")
            
        logger.info(f"Leave request {request_id} {action}d by {context.activity.from_property.id}")
        
    except Exception as e:
        logger.error(f"Error handling adaptive card action: {str(e)}")
        await context.send_activity(f"❌ Алдаа гарлаа: {str(e)}")

@app.route("/proactive-message", methods=["POST"])
def proactive_message():
    data = request.json
    message_text = data.get("message", "Сайн байна уу!")
    user_id = data.get("user_id")  # Тодорхой хэрэглэгч рүү мессеж илгээх
    
    try:
        if user_id:
            # Тодорхой хэрэглэгч рүү мессеж илгээх
            conversation_reference = load_conversation_reference(user_id)
            if not conversation_reference:
                return jsonify({"error": f"User {user_id} not found"}), 404
        else:
            # Хуучин арга: conversation_reference.json файлаас унших
            try:
                with open("conversation_reference.json", "r", encoding="utf-8") as f:
                    ref_data = json.load(f)
                conversation_reference = ConversationReference().deserialize(ref_data)
            except FileNotFoundError:
                return jsonify({"error": "No conversation reference found. Please specify user_id or ensure at least one user has messaged the bot."}), 404
        
        # Дэлгэрэнгүй log
        logger.info("=== Proactive message info ===")
        logger.info(f"User ID: {conversation_reference.user.id}")
        logger.info(f"User Name: {getattr(conversation_reference.user, 'name', None)}")
        logger.info(f"Conversation ID: {conversation_reference.conversation.id}")
        logger.info(f"Conversation Type: {getattr(conversation_reference.conversation, 'conversation_type', None)}")
        logger.info(f"Service URL: {conversation_reference.service_url}")
        logger.info(f"Bot ID: {conversation_reference.bot.id}")
        logger.info(f"Tenant ID: {getattr(conversation_reference.conversation, 'tenant_id', None)}")
        logger.info(f"Channel ID: {conversation_reference.channel_id}")
        logger.info(f"Message to send: {message_text}")
        
        async def send_proactive(context: TurnContext):
            await context.send_activity(message_text)
        
        asyncio.run(
            ADAPTER.continue_conversation(
                conversation_reference,
                send_proactive,
                app_id
            )
        )
        logger.info("Proactive message sent successfully")
        return jsonify({"status": "ok", "user_id": conversation_reference.user.id}), 200
    except Exception as e:
        logger.error(f"Proactive message error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/broadcast", methods=["POST"])
def broadcast_message():
    """Бүх хэрэглэгч рүү мессеж илгээх"""
    data = request.json
    message_text = data.get("message", "Сайн байна уу!")
    
    users = list_all_users()
    if not users:
        return jsonify({"error": "No users found"}), 404
    
    results = []
    for user_info in users:
        user_id = user_info["user_id"]
        try:
            conversation_reference = load_conversation_reference(user_id)
            if conversation_reference:
                async def send_proactive(context: TurnContext):
                    await context.send_activity(message_text)
                
                asyncio.run(
                    ADAPTER.continue_conversation(
                        conversation_reference,
                        send_proactive,
                        app_id
                    )
                )
                results.append({
                    "user_id": user_id,
                    "email": user_info.get("email"),
                    "user_name": user_info.get("user_name"),
                    "status": "success"
                })
                logger.info(f"Message sent to user {user_id} ({user_info.get('email', 'No email')})")
            else:
                results.append({
                    "user_id": user_id,
                    "email": user_info.get("email"),
                    "user_name": user_info.get("user_name"),
                    "status": "failed",
                    "error": "Reference not found"
                })
        except Exception as e:
            results.append({
                "user_id": user_id,
                "email": user_info.get("email"),
                "user_name": user_info.get("user_name"),
                "status": "failed",
                "error": str(e)
            })
            logger.error(f"Failed to send message to user {user_id}: {str(e)}")
    
    return jsonify({"results": results, "total_users": len(users), "message": message_text}), 200

@app.route("/send-by-conversation", methods=["POST"])
def send_by_conversation():
    """Conversation ID-аар мессеж илгээх"""
    try:
        data = request.json
        conversation_id = data.get("conversation_id")
        message_text = data.get("message", "Сайн байна уу!")

        if not conversation_id:
            return jsonify({"error": "conversation_id is required"}), 400

        # Conversation ID-аар хэрэглэгч олох
        user_info = find_user_by_conversation_id(conversation_id)
        if not user_info:
            return jsonify({"error": f"User with conversation_id {conversation_id} not found"}), 404

        # Conversation reference унших
        conversation_reference = load_conversation_reference(user_info["user_id"])
        if not conversation_reference:
            return jsonify({"error": "Conversation reference not found"}), 404

        # Мессеж илгээх
        async def send_message(context: TurnContext):
            await context.send_activity(message_text)

        asyncio.run(
            ADAPTER.continue_conversation(
                conversation_reference,
                send_message,
                app_id
            )
        )

        logger.info(f"Message sent to conversation {conversation_id} (user: {user_info.get('email', 'N/A')})")
        return jsonify({
            "status": "success",
            "conversation_id": conversation_id,
            "user_email": user_info.get("email"),
            "user_name": user_info.get("user_name"),
            "message": message_text
        }), 200

    except Exception as e:
        logger.error(f"Send by conversation error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

@app.route("/approval-callback", methods=["POST"])
def approval_callback():
    """Adaptive card approval callback (backup endpoint)"""
    try:
        data = request.json
        action = data.get("action")
        request_id = data.get("request_id")
        
        logger.info(f"Approval callback: {action} for request {request_id}")
        
        return jsonify({"status": "received", "action": action, "request_id": request_id}), 200
    except Exception as e:
        logger.error(f"Approval callback error: {str(e)}")
        return jsonify({"error": str(e)}), 500

def save_pending_confirmation(user_id, request_data):
    """Хэрэглэгчийн баталгаажуулалтыг хүлээж буй мэдээллийг хадгалах"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_{safe_user_id}.json"
        
        confirmation_data = {
            "user_id": user_id,
            "request_data": request_data,
            "created_at": datetime.now().isoformat(),
            "status": "awaiting_confirmation"
        }
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(confirmation_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved pending confirmation for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save pending confirmation: {str(e)}")
        return False

def load_pending_confirmation(user_id):
    """Хэрэглэгчийн баталгаажуулалтыг хүлээж буй мэдээллийг унших"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load pending confirmation for user {user_id}: {str(e)}")
        return None

def delete_pending_confirmation(user_id):
    """Хэрэглэгчийн баталгаажуулалтыг хүлээж буй мэдээллийг устгах"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_{safe_user_id}.json"
        
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"Deleted pending confirmation for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete pending confirmation: {str(e)}")
        return False

def save_pending_rejection(manager_user_id, request_data):
    """Manager-н татгалзах шалтгааныг хүлээж буй мэдээллийг хадгалах"""
    try:
        safe_user_id = manager_user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_rejection_{safe_user_id}.json"
        
        rejection_data = {
            "manager_user_id": manager_user_id,
            "request_data": request_data,
            "created_at": datetime.now().isoformat(),
            "status": "awaiting_rejection_reason"
        }
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(rejection_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved pending rejection for manager {manager_user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save pending rejection: {str(e)}")
        return False

def load_pending_rejection(manager_user_id):
    """Manager-н татгалзах шалтгааныг хүлээж буй мэдээллийг унших"""
    try:
        safe_user_id = manager_user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_rejection_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load pending rejection for manager {manager_user_id}: {str(e)}")
        return None

def delete_pending_rejection(manager_user_id):
    """Manager-н татгалзах шалтгааныг хүлээж буй мэдээллийг устгах"""
    try:
        safe_user_id = manager_user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_rejection_{safe_user_id}.json"
        
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"Deleted pending rejection for manager {manager_user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete pending rejection: {str(e)}")
        return False

def is_confirmation_response(text):
    """Мессеж нь баталгаажуулалтын хариу эсэхийг шалгах"""
    text_lower = text.lower().strip()
    
    # Зөвшөөрөх үгүүд
    approve_words = [
        'тийм', 'зөв', 'yes', 'зөвшөөрнө', 'илгээ', 'ok', 'okay', 
        'зөвшөөрөх', 'баталгаажуулна', 'болно', 'тийм шүү', 'зөв байна', "tiim"
    ]
    
    # Татгалзах үгүүд  
    reject_words = [
        'үгүй', 'буруу', 'no', 'татгалзана', 'битгий', 'болохгүй',
        'засна', 'шинээр', 'дахин', 'өөрчлөх', 'зөв биш', 'ugui', 'ugu', 'gu', 'zasna', 'zasan', 'zasnaa'
    ]
    
    for word in approve_words:
        if word in text_lower:
            return "approve"
    
    for word in reject_words:
        if word in text_lower:
            return "reject"
    
    return None

def create_confirmation_message(parsed_data, user_email=None):
    """Баталгаажуулалтын мессеж үүсгэх"""
    message = f"""🔍 Таны чөлөөний хүсэлтээс дараах мэдээллийг олж авлаа:

📅 **Эхлэх огноо:** {parsed_data.get('start_date')}
📅 **Дуусах огноо:** {parsed_data.get('end_date')}  
⏰ **Хоногийн тоо:** {parsed_data.get('days')} хоног
🕒 **Цагийн тоо:** {parsed_data.get('inactive_hours')} цаг
💭 **Шалтгаан:** {parsed_data.get('reason')}

❓ **Энэ мэдээлэл зөв бөгөөд менежер руу илгээхийг зөвшөөрч байна уу?**

💬 Хариулна уу:
• **"Тийм"** эсвэл **"Зөв"** - Илгээх
• **"Үгүй"** эсвэл **"Засна"** - Засварлах"""
    
    # Planner tasks мэдээлэл нэмэх
    if user_email and PLANNER_AVAILABLE:
        try:
            tasks_info = get_user_planner_tasks(user_email)
            message += f"\n\n{tasks_info}"
        except Exception as e:
            logger.error(f"Failed to add planner tasks to confirmation: {str(e)}")

    return message

async def send_approved_request_to_manager(request_data, original_message):
    """Баталгаажуулсан чөлөөний хүсэлтийг менежер руу илгээх"""
    try:
        approver_conversation = load_conversation_reference(APPROVER_USER_ID)
        
        if approver_conversation:
            # Adaptive card үүсгэх
            approval_card = create_approval_card(request_data)
            
            async def notify_manager_with_card(ctx: TurnContext):
                adaptive_card_attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=approval_card
                )
                # Planner tasks мэдээлэл авах
                planner_info = ""
                if request_data.get("requester_email"):
                    try:
                        planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                    except Exception as e:
                        logger.error(f"Failed to get planner tasks for approved request: {str(e)}")
                
                message = MessageFactory.attachment(adaptive_card_attachment)
                message.text = f"📨 Баталгаажсан чөлөөний хүсэлт: {request_data['requester_name']}\n💬 Анхны мессеж: \"{original_message}\"\n✅ Хэрэглэгч баталгаажуулсан{planner_info}"
                await ctx.send_activity(message)
            
            await ADAPTER.continue_conversation(
                approver_conversation,
                notify_manager_with_card,
                app_id
            )
            logger.info(f"Approved leave request {request_data['request_id']} sent to manager")
        else: 
            logger.warning(f"Manager conversation reference not found for request {request_data['request_id']}")
    except Exception as e:
        logger.error(f"Error sending approved request to manager: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)