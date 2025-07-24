import os
import sys
import json
import traceback
from dataclasses import asdict
from datetime import datetime, timedelta
import aiohttp  # Added for HTTP requests to deployed servers
import re      # Added for hours parsing

from botbuilder.core import MemoryStorage, TurnContext, MessageFactory, CardFactory
from botbuilder.core.activity_handler import ActivityHandler
from botbuilder.schema import ChannelAccount, Activity, ActivityTypes, SuggestedActions, CardAction, ActionTypes
from teams import Application, ApplicationOptions, TeamsAdapter
from teams.ai import AIOptions
from teams.ai.models import AzureOpenAIModelOptions, OpenAIModel, OpenAIModelOptions
from teams.ai.planners import ActionPlanner, ActionPlannerOptions
from teams.ai.prompts import PromptManager, PromptManagerOptions
from teams.state import TurnState
from teams.feedback_loop_data import FeedbackLoopData

from config import Config
from planner_service import PlannerService
config = Config()

# Create AI components
model: OpenAIModel

model = OpenAIModel(
    OpenAIModelOptions(
        api_key=config.OPENAI_API_KEY,
        default_model=config.OPENAI_MODEL_NAME,
    )
)

prompts = PromptManager(PromptManagerOptions(prompts_folder=f"{os.getcwd()}/prompts"))

planner = ActionPlanner(
    ActionPlannerOptions(
        model=model,
        prompts=prompts,
        default_prompt="chat",
        enable_feedback_loop=True,
    )
)

# Define storage and application
storage = MemoryStorage()
bot_app = Application[TurnState](
    ApplicationOptions(
        bot_app_id=config.APP_ID,
        storage=storage,
        adapter=TeamsAdapter(config),
        ai=AIOptions(planner=planner, enable_feedback_loop=True),
    )
)

# Store conversation references for users to send proactive messages
conversation_references = {}

def convert_quick_date_to_actual(quick_option: str) -> str:
    """Convert quick date option to actual date string"""
    today = datetime.now()
    
    if quick_option == "today":
        return today.strftime("%Y-%m-%d")
    elif quick_option == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif quick_option == "day_after_tomorrow":
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    elif quick_option == "next_monday":
        days_ahead = 0 - today.weekday()  # Monday is 0
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    elif quick_option == "next_tuesday":
        days_ahead = 1 - today.weekday()  # Tuesday is 1
        if days_ahead <= 0:
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    elif quick_option == "next_wednesday":
        days_ahead = 2 - today.weekday()  # Wednesday is 2
        if days_ahead <= 0:
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    elif quick_option == "next_thursday":
        days_ahead = 3 - today.weekday()  # Thursday is 3
        if days_ahead <= 0:
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    elif quick_option == "next_friday":
        days_ahead = 4 - today.weekday()  # Friday is 4
        if days_ahead <= 0:
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    else:
        return ""

def parse_hours_to_number(hours_text: str) -> float:
    """Parse hours text to numeric value for MCP server"""
    hours_text = hours_text.lower()
    
    # Extract number patterns first
    number_match = re.search(r'(\d+(?:\.\d+)?)', hours_text)
    
    if "бүтэн өдөр" in hours_text or "full day" in hours_text or "8" in hours_text:
        return 8.0
    elif "хагас өдөр" in hours_text or "half day" in hours_text or "4" in hours_text:
        return 4.0
    elif number_match:
        return float(number_match.group(1))
    else:
        # Default to 8 hours if unclear
        return 8.0

async def create_absence_request_mcp(user_email: str, start_date: str, end_date: str, reason: str, hours: str) -> bool:
    """Create absence request in MCP server"""
    try:
        # Parse hours to numeric value
        in_active_hours = parse_hours_to_number(hours)
        
        # Prepare the request payload
        payload = {
            "function": "create_absence_request",
            "args": {
                "user_email": user_email,
                "start_date": start_date,
                "end_date": end_date,
                "reason": reason,
                "in_active_hours": in_active_hours
            }
        }
        
        # Make HTTP request to MCP server
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{config.MCP_SERVER_URL}/call-function",
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ MCP response: {result}")
                    return True
                else:
                    print(f"❌ MCP error: {response.status} - {await response.text()}")
                    return False
                    
    except Exception as e:
        print(f"❌ Error calling MCP server: {e}")
        return False

async def test_mcp_server_connection() -> bool:
    """Test if MCP server is accessible"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{config.MCP_SERVER_URL}/",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return response.status == 200
    except Exception as e:
        print(f"❌ MCP server connection test failed: {e}")
        return False

async def send_teams_webhook_notification(user_name: str, user_email: str, start_date: str, end_date: str, hours: str, reason: str, status: str, manager_name: str = "Manager") -> bool:
    """Send notification to Teams webhook"""
    try:
        # Determine status color and emoji
        if status == "approved":
            status_color = "Good"
            status_emoji = "✅"
            status_text = "ЗӨВШӨӨРӨГДЛӨӨ"
        elif status == "rejected":
            status_color = "Attention"
            status_emoji = "❌"
            status_text = "ТАТГАЛЗАГДЛАА"
        else:
            status_color = "Warning"
            status_emoji = "⏳"
            status_text = "ХҮЛЭЭГДЭЖ БАЙ"
        
        # Create Teams message card
        teams_message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": f"Чөлөөний хүсэлт {status_text}",
            "themeColor": status_color,
            "sections": [
                {
                    "activityTitle": f"{status_emoji} **Чөлөөний хүсэлт {status_text}**",
                    "activitySubtitle": f"Хүсэгч: {user_name}",
                    "activityImage": "https://cdn-icons-png.flaticon.com/512/1077/1077114.png",
                    "facts": [
                        {
                            "name": "👤 Хүсэгч:",
                            "value": user_name
                        },
                        {
                            "name": "📧 И-мэйл:",
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
                            "name": "⏰ Цагийн хэмжээ:",
                            "value": hours
                        },
                        {
                            "name": "📝 Шалтгаан:",
                            "value": reason
                        },
                        {
                            "name": "👨‍💼 Шийдвэрлэсэн:",
                            "value": manager_name
                        },
                        {
                            "name": "📊 Төлөв:",
                            "value": f"{status_emoji} {status_text}"
                        }
                    ],
                    "markdown": True
                }
            ]
        }
        
        # Send to Teams webhook
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.TEAMS_WEBHOOK_URL,
                json=teams_message,
                headers={'Content-Type': 'application/json'},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status == 200:
                    print(f"✅ Teams webhook мэдэгдэл илгээгдлээ: {status_text}")
                    return True
                else:
                    print(f"❌ Teams webhook алдаа: {response.status} - {await response.text()}")
                    return False
                    
    except Exception as e:
        print(f"❌ Teams webhook илгээхэд алдаа: {e}")
        return False

def get_display_date(date_str: str, quick_option: str = "") -> str:
    """Convert date string to display format with day name"""
    try:
        # Try to parse the date
        if "-" in date_str:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            return date_str  # Return as is if not in expected format
        
        # Get Mongolian day names
        mongolian_days = {
            0: "Даваа",
            1: "Мягмар", 
            2: "Лхагва",
            3: "Пүрэв",
            4: "Баасан",
            5: "Бямба",
            6: "Ням"
        }
        
        day_name = mongolian_days.get(date_obj.weekday(), "")
        formatted_date = date_obj.strftime("%Y-%m-%d")
        
        return f"{formatted_date} ({day_name})"
    except:
        return date_str  # Return original if parsing fails

async def analyze_leave_intent_with_ai(context: TurnContext, message_text: str) -> bool:
    """Use GPT-4 to naturally understand if this is a leave request"""
    try:
        # Use the actual AI model to understand intent
        prompt = f"""
Та энэ мессежийг уншиж, хүн ажлаас чөлөө авахыг хүсэж байгаа эсэхийг ойлгоно уу.

Хэрэглэгчийн мессеж: "{message_text}"

Энэ мессеж монгол хэл, англи хэл, эсвэл латин үсгээр бичигдсэн монгол хэл байж болно.

Чөлөөний хүсэлтийн шинж тэмдгүүд:
- Чөлөө авах гэж байгаа (чөлөө, амрах, leave, chuluu, avmaar, avii)
- Огноо, цаг дурьдаж байгаа  
- Эрүүл мэндийн шалтгаан (өвчтэй, эмнэлэг, emnelg, emnelgeer, ovchtei)
- Хувийн асуудал (хувийн, personal, ger bul)
- Ажилд ирэхгүй байх (ажилд ирэхгүй, ирж чадахгүй, can't come to work)

Хэрэв энэ нь чөлөөний хүсэлт бол "ТИЙМ", үгүй бол "ҮГҮЙ" гэж хариулна уу.
"""

        # Use OpenAI directly for intent analysis
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": "Та олон хэлээр, ялангуяа монгол хэлээр чөлөөний хүсэлтийг ойлгодог мэргэжилтэн. Хүүхдийн хэлээр ч, албан ёсны хэлээр ч бичигдсэн байсан ойлгож чаддаг."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10,
            temperature=0.1
        )
        
        # Check the response
        content = response.choices[0].message.content
        if not content:
            print(f"🤖 GPT-4 intent analysis: No response content")
            return False
            
        result = content.strip().upper()
        print(f"🤖 GPT-4 ойлголт: '{result}' - '{message_text}' мессежид")
        
        return "ТИЙМ" in result or "YES" in result
        
    except Exception as e:
        print(f"Error in GPT-4 intent analysis: {e}")
        # Simple fallback only if GPT-4 fails
        basic_patterns = ["чөлөө", "амрах", "leave", "chuluu", "avmaar", "avii", "өвчтэй", "emnelg"]
        return any(pattern in message_text.lower() for pattern in basic_patterns)

def format_extracted_info(partial_data: dict) -> str:
    """Format extracted information for display"""
    formatted_parts = []
    
    if partial_data.get("start_date"):
        formatted_parts.append(f"📅 Эхлэх өдөр: {partial_data['start_date']}")
    if partial_data.get("end_date"):
        formatted_parts.append(f"📅 Дуусах өдөр: {partial_data['end_date']}")
    if partial_data.get("hours"):
        formatted_parts.append(f"⏰ Цагийн хэмжээ: {partial_data['hours']}")
    if partial_data.get("reason"):
        formatted_parts.append(f"📝 Шалтгаан: {partial_data['reason']}")
    
    return "\n".join(formatted_parts) if formatted_parts else "❌ Мэдээлэл олдсонгүй"

async def extract_leave_info_with_ai(context: TurnContext, message_text: str, user_name: str) -> dict:
    """Use GPT-4 to extract leave request information naturally"""
    
    try:
        today = datetime.now()
        
        # Use GPT-4 for smart extraction
        extraction_prompt = f"""
Та чөлөөний хүсэлтийн мэдээллийг энэ мессежээс авна уу. Өнөөдрийн огноо {today.strftime('%Y-%m-%d (%A)')}.

Хэрэглэгчийн мессеж: "{message_text}"

Энэ мессеж монгол хэл, англи хэл, эсвэл латин үсгээр бичигдсэн монгол хэл байж болно.

Дараах мэдээллийг авна уу:
1. Эхлэх огноо (формат: YYYY-MM-DD)
2. Дуусах огноо (формат: YYYY-MM-DD) 
3. Цагийн хэмжээ (ж.нь: "2 цаг", "бүтэн өдөр", "хагас өдөр", "өглөөний хагас")
4. Шалтгаан (эрүүл мэндийн асуудал = "Эрүүл мэндийн асуудал", хувийн асуудал = "Хувийн асуудал")

Огнооны жишээнүүд:
- "өнөөдөр/today/unooder" = өнөөдөр
- "маргааш/tomorrow/margaash" = маргааш
- "нөгөөдөр" = нөгөөдрийн дараа
- "дараагийн даваа/next monday" = дараагийн Даваа гариг
- "7 хоногийн 1-нд" = дараагийн Даваа гариг

JSON форматаар хариулна уу:
{{
    "start_date": "YYYY-MM-DD эсвэл хоосон",
    "end_date": "YYYY-MM-DD эсвэл хоосон", 
    "hours": "цагийн тайлбар эсвэл хоосон",
    "reason": "шалтгаан эсвэл хоосон"
}}

Зөвхөн JSON хариулна уу.
"""

        # Use OpenAI for extraction
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": "Та олон хэлээр бичигдсэн чөлөөний хүсэлтээс мэдээлэл авч чаддаг мэргэжилтэн. Монгол хүмүүсийн хэлэх хэв маягийг сайн ойлгодог."},
                {"role": "user", "content": extraction_prompt}
            ],
            max_tokens=200,
            temperature=0.1
        )
        
        # Parse the JSON response
        content = response.choices[0].message.content
        if not content:
            print(f"🤖 GPT-4 мэдээлэл авах: Хариу алга")
            return fallback_extraction(message_text, today)
            
        json_text = content.strip()
        print(f"🤖 GPT-4 мэдээлэл: {json_text}")
        
        extracted_data = json.loads(json_text)
        
        # Process the extracted data
        result = {
            "start_date": extracted_data.get("start_date", ""),
            "end_date": extracted_data.get("end_date", ""),
            "hours": extracted_data.get("hours", ""),
            "reason": extracted_data.get("reason", ""),
            "missing": [],
            "complete": False,
            "partial_data": {}
        }
        
        # Check what's missing
        if not result["start_date"]:
            result["missing"].append("start_date")
        if not result["end_date"]:
            result["missing"].append("end_date")
        if not result["hours"]:
            result["missing"].append("hours")
        if not result["reason"]:
            result["missing"].append("reason")
        
        # Set completion status
        result["complete"] = len(result["missing"]) == 0
        
        # Build partial data
        for key in ["start_date", "end_date", "hours", "reason"]:
            if result[key]:
                result["partial_data"][key] = result[key]
        
        print(f"🔍 Боловсруулсан үр дүн: {result}")
        return result
        
    except Exception as e:
        print(f"Error in GPT-4 extraction: {e}")
        # Fallback to pattern matching if GPT-4 fails
        return fallback_extraction(message_text, datetime.now())

def smart_extraction(message_text: str, today: datetime) -> dict:
    """Natural intelligent extraction - like human understanding"""
    
    # Debug output
    print(f"🔍 Smart extraction analyzing: '{message_text}'")
    
    result = {
        "start_date": "",
        "end_date": "", 
        "hours": "",
        "reason": "",
        "missing": [],
        "complete": False,
        "partial_data": {}
    }
    
    text_lower = message_text.lower()
    print(f"🔍 Lowercased text: '{text_lower}'")
    
    # Enhanced date extraction with natural understanding
    if "өнөөдөр" in text_lower or "today" in text_lower or "unooder" in text_lower:
        result["start_date"] = today.strftime("%Y-%m-%d")
        print(f"🔍 Date pattern matched: today -> {result['start_date']}")
    elif "маргааш" in text_lower or "margaash" in text_lower or "tomorrow" in text_lower:
        result["start_date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"🔍 Date pattern matched: tomorrow -> {result['start_date']}")
    elif "нөгөөдөр" in text_lower or "nugeedr" in text_lower or "day after tomorrow" in text_lower:
        result["start_date"] = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        print(f"🔍 Date pattern matched: day after tomorrow -> {result['start_date']}")
    elif "daraa 7 honogiin 1dehed" in text_lower or ("daraa 7 honogiin" in text_lower and "1dehed" in text_lower):
        # Next week on the 1st - calculate next Monday and add days to get to the 1st
        days_ahead = 7 - today.weekday()  # Days to next Monday
        next_monday = today + timedelta(days=days_ahead)
        # Add days to get to the 1st of next week (assuming 1st = Monday)
        result["start_date"] = next_monday.strftime("%Y-%m-%d")
        print(f"🔍 Date pattern matched: next week 1st -> {result['start_date']}")
    elif "7 honogiin 1dehed" in text_lower or "next week 1st" in text_lower:
        # Next week on the 1st - calculate next Monday
        days_ahead = 7 - today.weekday()  # Days to next Monday
        next_monday = today + timedelta(days=days_ahead)
        result["start_date"] = next_monday.strftime("%Y-%m-%d")
        print(f"🔍 Date pattern matched: week 1st -> {result['start_date']}")
    
    # Enhanced hours extraction - natural patterns
    hours_patterns = [
        # Specific hours with transliteration
        (["2 tsagiin", "2 tsag", "2 цаг", "2tsag", "hoyr tsag"], "⏰ 2 цаг"),
        (["1 tsagiin", "1 tsag", "1 цаг", "1tsag", "neg tsag"], "⏰ 1 цаг"),
        (["3 tsagiin", "3 tsag", "3 цаг", "3tsag", "gurav tsag"], "⏰ 3 цаг"),
        (["4 tsagiin", "4 tsag", "4 цаг", "4tsag", "durvun tsag"], "⏰ 4 цаг"),
        
        # Half/full day expressions
        (["бүтэн өдөр", "buten udur", "buten", "buten udrin", "full day", "8 tsag", "8 цаг"], "🌞 Бүтэн өдөр (8 цаг)"),
        (["хагас өдөр", "hagas udur", "hagas", "half day", "4 tsag"], "🌅 Хагас өдөр (4 цаг)"),
        (["өглөөний хагас", "ugluunii hagas", "morning half"], "🌅 Өглөөний хагас өдөр (4 цаг)"),
        (["үдээс хойш", "udees hoish", "afternoon half"], "🌇 Үдээс хойшхи хагас өдөр (4 цаг)")
    ]
    
    for patterns, hour_text in hours_patterns:
        for pattern in patterns:
            if pattern in text_lower:
                result["hours"] = hour_text
                print(f"🔍 Hours pattern matched: '{pattern}' -> {hour_text}")
                break
        if result["hours"]:
            break
    
    # Natural reason extraction
    reason_patterns = [
        # Health reasons - enhanced with more transliterated patterns
        (["өвчтэй", "ovchtei", "uvchin", "sick", "эмнэлэг", "emnelg", "emneleg", "emneegeer", 
          "emnelgeer", "hospital", "doctor", "эмч", "emch", "yvah", "yavah", "явах", "ajiltai", 
          "ajiltaimaa", "ажилтай"], "Эрүүл мэндийн асуудал"),
        
        # Personal reasons  
        (["хувийн", "huviin", "personal", "хувь", "huv"], "Хувийн асуудал"),
        
        # Family reasons
        (["гэр бүл", "ger bul", "family", "гэрийн", "geriin"], "Гэр бүлийн асуудал"),
        
        # Urgent reasons
        (["яаралтай", "yaaralttai", "urgent", "emergency", "яарал"], "Яаралтай асуудал"),
        
        # Default for basic leave patterns
        (["chuluu avmaar", "chuluu avii", "авмаар байна", "avmaar baina", "чөлөө авах"], "Хувийн асуудал")
    ]
    
    for patterns, reason_text in reason_patterns:
        for pattern in patterns:
            if pattern in text_lower:
                result["reason"] = reason_text
                print(f"🔍 Reason pattern matched: '{pattern}' -> {reason_text}")
                break
        if result["reason"]:
            break
    
    # Smart end date inference - human-like logic
    if result["start_date"]:
        # If hours specified but no end date, assume single day
        if result["hours"] and not result["end_date"]:
            result["end_date"] = result["start_date"]
        # If no hours and no end date, assume single day
        elif not result["end_date"]:
            result["end_date"] = result["start_date"]
    
    # Natural completion logic
    if not result["start_date"]:
        result["missing"].append("start_date")
    if not result["end_date"]:
        result["missing"].append("end_date")  
    if not result["hours"]:
        result["missing"].append("hours")
    if not result["reason"]:
        result["missing"].append("reason")
    
    # Natural completion - more flexible
    result["complete"] = len(result["missing"]) == 0
    
    # Build partial data naturally
    for key in ["start_date", "end_date", "hours", "reason"]:
        if result[key]:
            result["partial_data"][key] = result[key]
    
    return result

def fallback_extraction(message_text: str, today: datetime) -> dict:
    """Fallback extraction when AI fails"""
    
    # Debug output
    print(f"🔍 Fallback extraction analyzing: '{message_text}'")
    
    result = {
        "start_date": "",
        "end_date": "", 
        "hours": "",
        "reason": "",
        "missing": [],
        "complete": False,
        "partial_data": {}
    }
    
    text_lower = message_text.lower()
    print(f"🔍 Fallback lowercased text: '{text_lower}'")
    
    # Extract dates
    if "өнөөдөр" in text_lower or "today" in text_lower:
        result["start_date"] = today.strftime("%Y-%m-%d")
    elif "маргааш" in text_lower or "margaash" in text_lower or "tomorrow" in text_lower:
        result["start_date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "нөгөөдөр" in text_lower:
        result["start_date"] = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    elif "daraa 7 honogiin 1dehed" in text_lower or ("daraa 7 honogiin" in text_lower and "1dehed" in text_lower):
        days_ahead = 7 - today.weekday()  # Days to next Monday
        next_monday = today + timedelta(days=days_ahead)
        result["start_date"] = next_monday.strftime("%Y-%m-%d")
    elif "7 honogiin 1dehed" in text_lower:
        days_ahead = 7 - today.weekday()  # Days to next Monday
        next_monday = today + timedelta(days=days_ahead)
        result["start_date"] = next_monday.strftime("%Y-%m-%d")
    
    # Extract hours - support both Mongolian and transliterated
    if "2 tsag" in text_lower or "2 цаг" in text_lower or "2tsag" in text_lower:
        result["hours"] = "⏰ 2 цаг"
    elif "1 tsag" in text_lower or "1 цаг" in text_lower:
        result["hours"] = "⏰ 1 цаг"
    elif "бүтэн өдөр" in text_lower or "buten udur" in text_lower or "buten udrin" in text_lower:
        result["hours"] = "🌞 Бүтэн өдөр (8 цаг)"
    elif "хагас өдөр" in text_lower or "hagas udur" in text_lower:
        result["hours"] = "🌅 Хагас өдөр (4 цаг)"
    
    # Extract reason
    if ("өвчтэй" in text_lower or "ovchtei" in text_lower or "emneegeer" in text_lower or 
        "emnelgeer" in text_lower or "emnelg" in text_lower or "emneleg" in text_lower or 
        "yvah" in text_lower or "yavah" in text_lower or "ajiltai" in text_lower or 
        "ajiltaimaa" in text_lower or "эмнэлэг" in text_lower or "hospital" in text_lower or 
        "doctor" in text_lower):
        result["reason"] = "Эрүүл мэндийн асуудал"
    elif "хувийн" in text_lower or "huviin" in text_lower:
        result["reason"] = "Хувийн асуудал"
    
    # Set end date same as start date if not specified
    if result["start_date"] and not result["end_date"]:
        result["end_date"] = result["start_date"]
    
    # Check what's missing
    if not result["start_date"]:
        result["missing"].append("start_date")
    if not result["end_date"]:
        result["missing"].append("end_date")  
    if not result["hours"]:
        result["missing"].append("hours")
    if not result["reason"]:
        result["missing"].append("reason")
    
    # Set completion status
    result["complete"] = len(result["missing"]) == 0
    
    # Set partial data
    for key in ["start_date", "end_date", "hours", "reason"]:
        if result[key]:
            result["partial_data"][key] = result[key]
    
    return result

async def process_complete_leave_request(context: TurnContext, state: TurnState, user_name: str, user_email: str):
    """Process a complete leave request with all information available"""
    try:
        # Get task information
        planner_service = PlannerService()
        planner_tasks = planner_service.get_user_incomplete_tasks(user_email)
        personal_tasks = planner_service.get_personal_tasks(user_email)
        tasks_info = planner_service.format_tasks_for_display(planner_tasks, personal_tasks)
        
        # Send to manager
        success = await send_leave_request_to_manager(
            context,
            user_name,
            user_email,
            state.conversation.leave_request_data["start_date"],
            state.conversation.leave_request_data["end_date"],
            state.conversation.leave_request_data["hours"],
            state.conversation.leave_request_data["reason"],
            tasks_info
        )
        
        if success:
            await context.send_activity(
                "✅ **Чөлөөний хүсэлт амжилттай илгээгдлээ!**\n\n"
                f"📤 Manager (khuslen@fibo.cloud) руу дараах мэдээлэл илгээгдлээ:\n"
                f"• Эхлэх өдөр: {state.conversation.leave_request_data['start_date']}\n"
                f"• Дуусах өдөр: {state.conversation.leave_request_data['end_date']}\n"
                f"• Цагийн хэмжээ: {state.conversation.leave_request_data['hours']}\n"
                f"• Шалтгаан: {state.conversation.leave_request_data['reason']}\n"
                f"• Таны даалгавруудын төлөв\n\n"
                "🔔 Manager хариу өгөх хүртэл хүлээнэ үү."
            )
        else:
            await context.send_activity("❌ Алдаа гарлаа. Дахин оролдоно уу.")
            
    except Exception as e:
        print(f"Error in complete leave request processing: {e}")
        await context.send_activity("❌ Алдаа гарлаа. Дахин оролдоно уу.")
    
    # Reset state
    state.conversation.leave_request_state = LEAVE_REQUEST_STATES["START"]
    state.conversation.leave_request_data = {}

def add_conversation_reference(activity: Activity):
    """Store conversation reference for proactive messaging"""
    conversation_reference = TurnContext.get_conversation_reference(activity)
    if activity.from_property:
        user_id = (activity.from_property.email if hasattr(activity.from_property, 'email') and activity.from_property.email 
                  else activity.from_property.id)
        conversation_references[user_id] = conversation_reference

async def send_proactive_message(user_email: str, message_text: str):
    """Send a proactive message to a specific user"""
    try:
        if user_email in conversation_references:
            conversation_reference = conversation_references[user_email]
            
            async def callback(turn_context: TurnContext):
                await turn_context.send_activity(MessageFactory.text(message_text))
            
            await bot_app.adapter.continue_conversation(
                conversation_reference, 
                callback, 
                config.APP_ID
            )
            return True
        else:
            print(f"No conversation reference found for user: {user_email}")
            return False
    except Exception as e:
        print(f"Error sending proactive message: {e}")
        return False

# Leave request states
LEAVE_REQUEST_STATES = {
    "START": "start",
    "ASKING_START_DATE": "asking_start_date", 
    "ASKING_END_DATE": "asking_end_date",
    "ASKING_HOURS": "asking_hours",
    "ASKING_REASON": "asking_reason",
    "COMPLETED": "completed"
}

@bot_app.error
async def on_error(context: TurnContext, error: Exception):
    # This check writes out errors to console log .vs. app insights.
    # NOTE: In production environment, you should consider logging this to Azure
    #       application insights.
    print(f"\n [on_turn_error] unhandled error: {error}", file=sys.stderr)
    traceback.print_exc()

    # Send a message to the user
    await context.send_activity("The agent encountered an error or bug.")

@bot_app.feedback_loop()
async def feedback_loop(_context: TurnContext, _state: TurnState, feedback_loop_data: FeedbackLoopData):
    # Add custom feedback process logic here.
    print(f"Your feedback is:\n{json.dumps(asdict(feedback_loop_data), indent=4)}")

def create_date_picker_card(user_name: str, stage: str):
    """Create adaptive card with date picker for leave request"""
    if stage == "start_date":
        title = "📅 Чөлөө эхлэх өдөр сонгоно уу"
        submit_action = "select_start_date"
    else:  # end_date
        title = "📅 Чөлөө дуусах өдөр сонгоно уу"
        submit_action = "select_end_date"
    
    card = {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": f"🏖️ Чөлөөний хүсэлт - {user_name}",
                "size": "Large",
                "weight": "Bolder",
                "color": "Accent"
            },
            {
                "type": "TextBlock",
                "text": title,
                "size": "Medium",
                "weight": "Bolder",
                "spacing": "Medium"
            },
            {
                "type": "TextBlock",
                "size": "Small",
                "color": "Default",
                "spacing": "Small"
            },
            {
                "type": "Input.ChoiceSet",
                "id": "quick_date_option",
                "style": "compact",
                "placeholder": "💡 Хурдан сонголт хийх",
                "choices": [
                    {"title": "📅 Өнөөдөр", "value": "today"},
                    {"title": "📅 Маргааш", "value": "tomorrow"},
                    {"title": "📅 Нөгөөдөр", "value": "day_after_tomorrow"},
                    {"title": "📅 Дараагийн Даваа", "value": "next_monday"},
                    {"title": "📅 Дараагийн Мягмар", "value": "next_tuesday"},
                    {"title": "📅 Дараагийн Лхагва", "value": "next_wednesday"},
                    {"title": "📅 Дараагийн Пүрэв", "value": "next_thursday"},
                    {"title": "📅 Дараагийн Баасан", "value": "next_friday"},
                    {"title": "📝 Бусад өдөр (доор бичнэ үү)", "value": "custom"}
                ],
                "spacing": "Medium"
            },
            {
                "type": "TextBlock",
                "text": "**ЭСВЭЛ** доорх талбарт шууд бичнэ үү:",
                "size": "Small",
                "weight": "Bolder",
                "spacing": "Medium"
            },
            {
                "type": "Input.Text",
                "id": "custom_date",
                "placeholder": "Жишээ: 2024-01-15, Нэгдүгээр сарын 15, эсвэл 01/15",
                "spacing": "Small"
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Сонгох",
                "style": "positive",
                "data": {
                    "action": submit_action,
                    "stage": stage
                }
            },
            {
                "type": "Action.Submit",
                "title": "❌ Цуцлах",
                "style": "destructive", 
                "data": {
                    "action": "cancel_leave_request"
                }
            }
        ]
    }
    return CardFactory.adaptive_card(card)

def create_hours_picker_card(user_name: str):
    """Create adaptive card with hours selection for leave request"""
    card = {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": f"🏖️ Чөлөөний хүсэлт - {user_name}",
                "size": "Large",
                "weight": "Bolder",
                "color": "Accent"
            },
            {
                "type": "TextBlock",
                "text": "⏰ Хэдэн цаг чөлөө авах вэ?",
                "size": "Medium",
                "weight": "Bolder",
                "spacing": "Medium"
            },
            {
                "type": "Input.ChoiceSet",
                "id": "selected_hours",
                "style": "compact",
                "placeholder": "Цагийн хэмжээ сонгоно уу",
                "choices": [
                    {"title": "🌅 Өглөөний хагас өдөр (4 цаг)", "value": "morning_half"},
                    {"title": "🌇 Үдээс хойшхи хагас өдөр (4 цаг)", "value": "afternoon_half"},
                    {"title": "⏰ 1 цаг", "value": "1_hour"},
                    {"title": "⏰ 2 цаг", "value": "2_hours"},
                    {"title": "⏰ 3 цаг", "value": "3_hours"},
                    {"title": "🌞 Бүтэн өдөр (8 цаг)", "value": "full_day"},
                    {"title": "📝 Бусад (тэмдэглэлд бичнэ үү)", "value": "custom"}
                ],
                "spacing": "Medium"
            },
            {
                "type": "Input.Text",
                "id": "custom_hours",
                "placeholder": "Хэрэв 'Бусад' сонгосон бол энд бичнэ үү",
                "isMultiline": False,
                "spacing": "Small"
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Сонгох",
                "style": "positive",
                "data": {
                    "action": "select_hours"
                }
            },
            {
                "type": "Action.Submit",
                "title": "❌ Цуцлах",
                "style": "destructive", 
                "data": {
                    "action": "cancel_leave_request"
                }
            }
        ]
    }
    return CardFactory.adaptive_card(card)

def create_leave_request_card(user_name: str, user_email: str, start_date: str, end_date: str, reason: str, hours: str, tasks_info: str):
    """Create adaptive card for leave request approval"""
    card = {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": f"🏖️ Чөлөөний хүсэлт - {user_name}",
                "size": "Large",
                "weight": "Bolder",
                "color": "Accent"
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "👤 Хүсэгч:", "value": user_name},
                    {"title": "📧 И-мэйл:", "value": user_email},
                    {"title": "📅 Эхлэх өдөр:", "value": start_date},
                    {"title": "📅 Дуусах өдөр:", "value": end_date},
                    {"title": "⏰ Цагийн хэмжээ:", "value": hours},
                    {"title": "📝 Шалтгаан:", "value": reason}
                ]
            },
            {
                "type": "TextBlock",
                "text": "Даалгавруудын төлөв:",
                "weight": "Bolder",
                "size": "Medium",
                "spacing": "Medium"
            },
            {
                "type": "TextBlock",
                "text": tasks_info,
                "wrap": True,
                "spacing": "Small"
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Зөвшөөрөх",
                "style": "positive",
                "data": {
                    "action": "approve_leave",
                    "user_email": user_email,
                    "user_name": user_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "hours": hours,
                    "reason": reason
                }
            },
            {
                "type": "Action.Submit", 
                "title": "❌ Татгалзах",
                "style": "destructive",
                "data": {
                    "action": "reject_leave",
                    "user_email": user_email,
                    "user_name": user_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "hours": hours,
                    "reason": reason
                }
            }
        ]
    }
    return CardFactory.adaptive_card(card)

def create_updated_leave_request_card(user_name: str, user_email: str, start_date: str, end_date: str, reason: str, hours: str, tasks_info: str, status: str, manager_name: str = "Manager"):
    """Create updated adaptive card showing the decision (approved/rejected)"""
    
    # Determine status display
    if status == "approved":
        status_text = "✅ ЗӨВШӨӨРӨГДЛӨӨ"
        status_color = "Good"
    else:  # rejected
        status_text = "❌ ТАТГАЛЗАГДЛАА"
        status_color = "Attention"
    
    card = {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": f"🏖️ Чөлөөний хүсэлт - {user_name}",
                "size": "Large",
                "weight": "Bolder",
                "color": "Accent"
            },
            {
                "type": "TextBlock",
                "text": status_text,
                "size": "Large",
                "weight": "Bolder",
                "color": status_color,
                "spacing": "Medium"
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "👤 Хүсэгч:", "value": user_name},
                    {"title": "📧 И-мэйл:", "value": user_email},
                    {"title": "📅 Эхлэх өдөр:", "value": start_date},
                    {"title": "📅 Дуусах өдөр:", "value": end_date},
                    {"title": "⏰ Цагийн хэмжээ:", "value": hours},
                    {"title": "📝 Шалтгаан:", "value": reason},
                    {"title": "👨‍💼 Шийдвэрлэсэн:", "value": manager_name},
                    {"title": "📊 Төлөв:", "value": status_text}
                ]
            },
            {
                "type": "TextBlock",
                "text": "Даалгавруудын төлөв:",
                "weight": "Bolder",
                "size": "Medium",
                "spacing": "Medium"
            },
            {
                "type": "TextBlock",
                "text": tasks_info,
                "wrap": True,
                "spacing": "Small"
            },
            {
                "type": "TextBlock",
                "text": f"⏰ Шийдвэрлэсэн цаг: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "size": "Small",
                "color": "Default",
                "spacing": "Medium"
            }
        ]
        # No actions - buttons are removed after decision
    }
    return CardFactory.adaptive_card(card)

async def send_leave_request_to_manager(context: TurnContext, user_name: str, user_email: str, start_date: str, end_date: str, hours: str, reason: str, tasks_info: str):
    """Send leave request to manager with approval buttons"""
    try:
        # Create the adaptive card
        card_attachment = create_leave_request_card(user_name, user_email, start_date, end_date, reason, hours, tasks_info)
        
        # Create message activity for manager
        manager_message = MessageFactory.attachment(card_attachment)
        manager_message.text = f"Шинэ чөлөөний хүсэлт {user_name}-аас"
        
        # Create manager channel account
        manager_account = ChannelAccount(id="khuslen@fibo.cloud", name="Manager")
        
        # TODO: In real implementation, send proactive message to manager
        # For now, we'll simulate sending to manager without showing the card to the requester
        print(f"[SIMULATED] Sending leave request card to manager for {user_name}")
        print(f"Request details: {start_date} - {end_date}, {hours}, {reason}")
        
        # Try to send proactive message to manager if possible
        manager_email = "khuslen@fibo.cloud"
        
        # Send a simple notification to manager (if conversation reference exists)
        manager_notification = (
            f"🏖️ **Шинэ чөлөөний хүсэлт**\n\n"
            f"👤 Хүсэгч: {user_name} ({user_email})\n"
            f"📅 Хугацаа: {start_date} - {end_date}\n"
            f"⏰ Цагийн хэмжээ: {hours}\n"
            f"📝 Шалтгаан: {reason}\n\n"
            f"📋 Даалгавруудын төлөв:\n{tasks_info}\n\n"
            f"💡 Зөвшөөрөх/Татгалзахын тулд Teams app-д орно уу."
        )
        
        # Attempt to send proactive message to manager
        manager_message_sent = await send_proactive_message(manager_email, manager_notification)
        
        if manager_message_sent:
            print(f"✅ Proactive message sent to manager: {manager_email}")
        else:
            print(f"⚠️ Could not send proactive message to manager: {manager_email}")
        
        return True
        
    except Exception as e:
        print(f"Error sending leave request: {e}")
        return False

@bot_app.activity("message")
async def on_message_activity(context: TurnContext, state: TurnState):
    """
    Handle all incoming messages and manage leave request workflow
    """
    try:
        # Store conversation reference for proactive messaging
        add_conversation_reference(context.activity)
        
        # Get user information
        user_name = context.activity.from_property.name if context.activity.from_property else "User"
        
        # Extract first name and create proper email
        if (context.activity.from_property and 
            hasattr(context.activity.from_property, 'email') and 
            context.activity.from_property.email):
            user_email = context.activity.from_property.email
        else:
            # Extract first name from display name and create email
            first_name = user_name.split()[0].lower() if user_name and ' ' in user_name else user_name.lower()
            user_email = f"{first_name}@fibo.cloud"
        
        print(f"user_name --> {user_name}")
        print(f"user_email --> {user_email}")
        
        # Get message text
        message_text = context.activity.text.strip().lower() if context.activity.text else ""
        
        # Initialize leave request state if not exists
        if not hasattr(state.conversation, 'leave_request_state'):
            state.conversation.leave_request_state = LEAVE_REQUEST_STATES["START"]
            state.conversation.leave_request_data = {}
        
        # AI-powered leave request detection and processing
        # Use OpenAI model to analyze if this is a leave request
        try:
            # Use the existing AI model to analyze the message
            is_leave_request = await analyze_leave_intent_with_ai(context, message_text)
            
            if is_leave_request:
                # Extract leave information using AI
                extracted_info = await extract_leave_info_with_ai(context, message_text, user_name)
                
                if extracted_info["complete"]:
                    # All required info extracted, proceed directly
                    state.conversation.leave_request_data = {
                        "start_date": extracted_info["start_date"],
                        "end_date": extracted_info["end_date"], 
                        "hours": extracted_info["hours"],
                        "reason": extracted_info["reason"]
                    }
                    state.conversation.leave_request_state = LEAVE_REQUEST_STATES["COMPLETED"]
                    
                    # Show extracted information
                    await context.send_activity(
                        f"😊 **Аа, ойлголоо! Та чөлөө авахыг хүсэж байна.**\n\n"
                        f"📅 Эхлэх өдөр: **{extracted_info['start_date']}**\n"
                        f"📅 Дуусах өдөр: **{extracted_info['end_date']}**\n"
                        f"⏰ Цагийн хэмжээ: **{extracted_info['hours']}**\n"
                        f"📝 Шалтгаан: **{extracted_info['reason']}**\n\n"
                        "⏳ Миний танд туслах зүйл бол manager-т илгээх явдал. Түр хүлээнэ үү..."
                    )
                    
                    # Process the leave request immediately
                    await process_complete_leave_request(context, state, user_name, user_email)
                    return True
                    
                else:
                    # Partial info extracted, ask for missing details
                    missing_info = extracted_info["missing"]
                    state.conversation.leave_request_data = extracted_info["partial_data"]
                    
                    await context.send_activity(
                        f"😊 **Аа, та чөлөө авахыг хүсэж байна шүү!**\n\n"
                        f"🔍 Таны хэлсэн зүйлээс ойлгосон нь:\n"
                        f"{format_extracted_info(extracted_info['partial_data'])}\n\n"
                        f"🤔 Гэхдээ надад {', '.join(missing_info)} нь тодорхойгүй байна. Тодруулж өгөөч?"
                    )
                    
                    if "start_date" in missing_info:
                        state.conversation.leave_request_state = LEAVE_REQUEST_STATES["ASKING_START_DATE"]
                        await context.send_activity(
                            f"📅 **Хэзээнээс эхлэн чөлөө авмаар байна? Огноогоо хэлээрэй.**"
                        )
                    elif "end_date" in missing_info:
                        state.conversation.leave_request_state = LEAVE_REQUEST_STATES["ASKING_END_DATE"]
                        await context.send_activity(
                            f"📅 **Хэзээ хүртэл чөлөө авах гэж байна? Дуусах огноогоо хэлээрэй.**"
                        )
                    elif "hours" in missing_info:
                        state.conversation.leave_request_state = LEAVE_REQUEST_STATES["ASKING_HOURS"] 
                        await context.send_activity(
                            f"⏰ **Хэдэн цаг чөлөө авахыг хүсэж байна? Бүтэн өдөр үү, хагас өдөр үү?**"
                        )
                    elif "reason" in missing_info:
                        state.conversation.leave_request_state = LEAVE_REQUEST_STATES["ASKING_REASON"]
                        await context.send_activity(
                            f"📝 **Юуны учир чөлөө авахыг хүсэж байна? Хэлээрэй.**\n\n"
                            "💡 Жишээ нь:\n"
                            "• Хувийн асуудал\n"  
                            "• Өвчтэй байна\n"
                            "• Эмнэлэгт явах\n"
                            "• Гэр бүлийн асуудал\n"
                            "• Яаралтай асуудал"
                        )
                    return True
            else:
                # Not a leave request, continue with normal processing
                return False
                    
        except Exception as e:
            print(f"Error in AI analysis: {e}")
            # Continue with normal processing if AI fails
            return False
            
        # Handle leave request workflow
        if state.conversation.leave_request_state == LEAVE_REQUEST_STATES["ASKING_START_DATE"]:
            # Parse start date
            state.conversation.leave_request_data["start_date"] = message_text
            state.conversation.leave_request_state = LEAVE_REQUEST_STATES["ASKING_END_DATE"]
            
            await context.send_activity(
                f"😊 Ойлголоо, **{message_text}**-нээс эхэлнэ.\n\n"
                "📅 **Одоо хэзээ хүртэл чөлөөтэй байхыг хүсэж байгаагаа хэлээрэй?**\n"
                "*(Жишээ: 2024-01-20, 3 өдрийн дараа, дараагийн баасан гэх мэт)*"
            )
            return True
            
        elif state.conversation.leave_request_state == LEAVE_REQUEST_STATES["ASKING_END_DATE"]:
            # Parse end date
            state.conversation.leave_request_data["end_date"] = message_text
            state.conversation.leave_request_state = LEAVE_REQUEST_STATES["ASKING_HOURS"]
            
            await context.send_activity(
                f"👍 Тэгвэл **{message_text}** хүртэл.\n\n"
                "⏰ **Хэдэн цагийн хэмжээнд чөлөө авахыг хүсэж байна?**\n"
                "*(Жишээ: бүтэн өдөр, хагас өдөр, 2 цаг, өглөөний хагас гэх мэт)*"
            )
            return True
            
        elif state.conversation.leave_request_state == LEAVE_REQUEST_STATES["ASKING_HOURS"]:
            # Parse hours
            state.conversation.leave_request_data["hours"] = message_text
            state.conversation.leave_request_state = LEAVE_REQUEST_STATES["ASKING_REASON"]
            
            await context.send_activity(
                f"👌 **{message_text}** цагийн хэмжээнд.\n\n"
                "📝 **Сүүлд, юуны учир чөлөө авахыг хүсэж байгаагаа хэлээрэй:**\n\n"
                "💡 Жишээ нь:\n"
                "• Хувийн асуудал\n"  
                "• Өвчтэй байна\n"
                "• Эмнэлэгт явах\n"
                "• Гэр бүлийн асуудал\n"
                "• Яаралтай асуудал"
            )
            return True
            
        elif state.conversation.leave_request_state == LEAVE_REQUEST_STATES["ASKING_REASON"]:
            # Save reason and complete request
            state.conversation.leave_request_data["reason"] = message_text
            state.conversation.leave_request_state = LEAVE_REQUEST_STATES["COMPLETED"]
            
            await context.send_activity(
                f"😌 Ойлголоо, **{message_text}** шалтгаантай.\n\n"
                "⏳ Одоо би таны хүсэлтийг manager-т илгээх бэлтгэл хийж байна...\n"
                "📊 Таны даалгавруудын төлөвийг шалгаад хамт илгээх болно."
            )
            
            # Get task information
            try:
                planner_service = PlannerService()
                planner_tasks = planner_service.get_user_incomplete_tasks(user_email)
                personal_tasks = planner_service.get_personal_tasks(user_email)
                tasks_info = planner_service.format_tasks_for_display(planner_tasks, personal_tasks)
                
                # Send to manager
                success = await send_leave_request_to_manager(
                    context,
                    user_name,
                    user_email,
                    state.conversation.leave_request_data["start_date"],
                    state.conversation.leave_request_data["end_date"],
                    state.conversation.leave_request_data.get("hours", "Тодорхойгүй"),
                    state.conversation.leave_request_data["reason"],
                    tasks_info
                )
                
                if success:
                    await context.send_activity(
                        "🎉 **Бүх зүйл болсон! Таны хүсэлт manager-т хүрлээ.**\n\n"
                        f"📤 Manager (khuslen@fibo.cloud) руу илгээгдсэн мэдээлэл:\n"
                        f"• Эхлэх өдөр: {state.conversation.leave_request_data['start_date']}\n"
                        f"• Дуусах өдөр: {state.conversation.leave_request_data['end_date']}\n"
                        f"• Цагийн хэмжээ: {state.conversation.leave_request_data.get('hours', 'Тодорхойгүй')}\n"
                        f"• Шалтгаан: {state.conversation.leave_request_data['reason']}\n"
                        f"• Таны одоогийн даалгавруудын төлөв\n\n"
                        "⏰ Одоо manager хариулах хүртэл хүлээх л үлдлээ. Би танд мэдээлэх болно!"
                    )
                else:
                    await context.send_activity("😕 Уучлаарай, ямар нэгэн алдаа гарлаа. Дахин оролдоод үзэж болох уу?")
                    
            except Exception as e:
                print(f"Error in leave request completion: {e}")
                await context.send_activity("❌ Алдаа гарлаа. Дахин оролдоно уу.")
            
            # Reset state
            state.conversation.leave_request_state = LEAVE_REQUEST_STATES["START"]
            state.conversation.leave_request_data = {}
            return True
        
        # Regular task checking for non-leave requests
        if state.conversation.leave_request_state == LEAVE_REQUEST_STATES["START"]:
            # Get real planner data using client credentials
            try:
                planner_service = PlannerService()
                
                # Get incomplete tasks from both planner and personal tasks (sync calls)
                planner_tasks = planner_service.get_user_incomplete_tasks(user_email)
                personal_tasks = planner_service.get_personal_tasks(user_email)
                
                # Format tasks for display
                tasks_info = planner_service.format_tasks_for_display(planner_tasks, personal_tasks)
                
                # Store task information in the conversation state
                state.conversation.tasks_info = tasks_info
                
                # Send the task information directly to the user
                await context.send_activity(f"👋 Сайн байна уу, {user_name}! Сайхан өдөр болоосой.\n\n{tasks_info}\n\n💡 **Хэрэв чөлөө авахыг хүсвэл надад хэлээрэй. Би танд тусалж чадна!**")
                
            except Exception as e:
                print(f"Error getting planner tasks: {e}")
                await context.send_activity(
                    f"😅 Уучлаарай, таны даалгавруудын мэдээллийг авахад бага зэрэг асуудал гарлаа.\n"
                    f"Техникийн алдаа: {str(e)}\n\n"
                    "💡 **Гэхдээ чөлөө авахыг хүсвэл надад хэлээрэй, би танд тусалж чадна!**"
                )
        
        # Continue with normal message processing
        return True
        
    except Exception as e:
        print(f"Error in message handler: {e}")
        await context.send_activity(
            "😅 Уучлаарай, би таныг ойлгож чадсангүй. Дахин асуугаад болох уу?"
        )
        return True

# Handle action submissions (button clicks)
@bot_app.activity("invoke")
async def on_invoke_activity(context: TurnContext, state: TurnState):
    """Handle adaptive card button submissions"""
    try:
        if context.activity.name == "adaptiveCard/action" and context.activity.value:
            action_data = context.activity.value
            action_type = action_data.get("action") if action_data else None
            
            # TEMPORARILY DISABLED: Adaptive card date/hours selection handlers
            # These will be re-enabled later when needed
            
            # Handle date selection for leave requests (DISABLED)
            # if action_type == "select_start_date":
            #     ...date picker logic...
            
            # elif action_type == "select_end_date":
            #     ...date picker logic...
                
            # elif action_type == "select_hours":
            #     ...hours picker logic...
                
            # elif action_type == "cancel_leave_request":
            #     ...cancel logic...
            
            if action_type == "approve_leave":
                user_name = action_data.get("user_name", "Unknown")
                start_date = action_data.get("start_date", "N/A")
                end_date = action_data.get("end_date", "N/A")
                hours = action_data.get("hours", "N/A")
                reason = action_data.get("reason", "N/A")
                user_email = action_data.get("user_email", "N/A")
                
                # Update the card to show approved status (remove buttons)
                try:
                    # Get task information for updated card
                    planner_service = PlannerService()
                    planner_tasks = planner_service.get_user_incomplete_tasks(user_email)
                    personal_tasks = planner_service.get_personal_tasks(user_email)
                    tasks_info = planner_service.format_tasks_for_display(planner_tasks, personal_tasks)
                    
                    # Create updated card with approved status
                    updated_card = create_updated_leave_request_card(
                        user_name, user_email, start_date, end_date, reason, hours, tasks_info, "approved", "Manager"
                    )
                    
                    # Update the original card that contained the buttons
                    update_activity = MessageFactory.attachment(updated_card)
                    update_activity.id = context.activity.id  # Use the current activity ID
                    await context.update_activity(update_activity)
                    
                except Exception as e:
                    print(f"Error updating card: {e}")
                    # If update fails, send new message
                    await context.send_activity(f"✅ **Картыг шинэчлэх чадахгүй байна, шийдвэр: ЗӨВШӨӨРӨГДЛӨӨ**")
                
                # Send confirmation to manager
                await context.send_activity(
                    f"👍 **Зөвшөөрлөө!**\n\n"
                    f"😊 {user_name}-ын хүсэлтийг зөвшөөрч өглөө.\n"
                    f"📅 {start_date} - {end_date}\n"
                    f"⏰ Цагийн хэмжээ: {hours}\n"
                    f"📝 Шалтгаан: {reason}\n\n"
                    f"📧 Одоо {user_email} руу мэдэгдэх болно...\n"
                    f"💾 Системд бүртгэж байна..."
                )
                
                # Create absence request in MCP server
                mcp_success = await create_absence_request_mcp(user_email, start_date, end_date, reason, hours)
                
                if mcp_success:
                    await context.send_activity(f"✅ MCP server-д амжилттай бүртгэгдлээ!")
                    
                    # Send Teams webhook notification
                    webhook_success = await send_teams_webhook_notification(
                        user_name, user_email, start_date, end_date, hours, reason, "approved", "Manager"
                    )
                    if webhook_success:
                        await context.send_activity(f"✅ Teams channel руу мэдэгдэл илгээгдлээ!")
                    else:
                        await context.send_activity(f"⚠️ Teams webhook илгээхэд алдаа гарлаа.")
                    
                    # Send approval message to the original requester
                    approval_message = (
                        f"✅ **Таны чөлөөний хүсэлт ЗӨВШӨӨРӨГДЛӨӨ!**\n\n"
                        f"📅 Хугацаа: {start_date} - {end_date}\n"
                        f"⏰ Цагийн хэмжээ: {hours}\n"
                        f"📝 Шалтгаан: {reason}\n\n"
                        f"💾 Системд бүртгэгдлээ\n"
                        f"🎉 Сайхан амраарай!"
                    )
                    
                    success = await send_proactive_message(user_email, approval_message)
                    if success:
                        await context.send_activity(f"🎉 {user_email} руу зөвшөөрсөн мэдэгдэл хүргэгдлээ!")
                    else:
                        await context.send_activity(f"😅 {user_email} руу шууд мэдэгдэл илгээхэд асуудал гарлаа.")
                else:
                    await context.send_activity(f"🤔 Системд бүртгэхэд асуудал гарсан байна. Админтай холбогдоорой.")
                    
                    # Still send approval message even if MCP fails
                    approval_message = (
                        f"✅ **Таны чөлөөний хүсэлт ЗӨВШӨӨРӨГДЛӨӨ!**\n\n"
                        f"📅 Хугацаа: {start_date} - {end_date}\n"
                        f"⏰ Цагийн хэмжээ: {hours}\n"
                        f"📝 Шалтгаан: {reason}\n\n"
                        f"⚠️ Систем алдаа: Админтай холбогдоно уу\n"
                        f"🎉 Сайхан амраарай!"
                    )
                    
                    await send_proactive_message(user_email, approval_message)
                
            if action_type == "reject_leave":
                user_name = action_data.get("user_name", "Unknown")
                start_date = action_data.get("start_date", "N/A")
                end_date = action_data.get("end_date", "N/A")
                hours = action_data.get("hours", "N/A")
                reason = action_data.get("reason", "N/A")
                user_email = action_data.get("user_email", "N/A")
                
                # Update the card to show rejected status (remove buttons)
                try:
                    # Get task information for updated card
                    planner_service = PlannerService()
                    planner_tasks = planner_service.get_user_incomplete_tasks(user_email)
                    personal_tasks = planner_service.get_personal_tasks(user_email)
                    tasks_info = planner_service.format_tasks_for_display(planner_tasks, personal_tasks)
                    
                    # Create updated card with rejected status
                    updated_card = create_updated_leave_request_card(
                        user_name, user_email, start_date, end_date, reason, hours, tasks_info, "rejected", "Manager"
                    )
                    
                    # Update the original card that contained the buttons
                    update_activity = MessageFactory.attachment(updated_card)
                    update_activity.id = context.activity.id  # Use the current activity ID
                    await context.update_activity(update_activity)
                    
                except Exception as e:
                    print(f"Error updating card: {e}")
                    # If update fails, send new message
                    await context.send_activity(f"❌ **Картыг шинэчлэх чадахгүй байна, шийдвэр: ТАТГАЛЗАГДЛАА**")
                
                # Send confirmation to manager
                await context.send_activity(
                    f"🙅‍♂️ **Татгалзлаа.**\n\n"
                    f"😔 {user_name}-ын хүсэлтийг татгалзах шийдвэр гаргалаа.\n"
                    f"📅 {start_date} - {end_date}\n"
                    f"⏰ Цагийн хэмжээ: {hours}\n"
                    f"📝 Шалтгаан: {reason}\n\n"
                    f"📧 Одоо {user_email} руу мэдэгдэх болно..."
                )
                
                # Send Teams webhook notification for rejection
                webhook_success = await send_teams_webhook_notification(
                    user_name, user_email, start_date, end_date, hours, reason, "rejected", "Manager"
                )
                if webhook_success:
                    await context.send_activity(f"✅ Teams channel руу татгалзсан мэдэгдэл илгээгдлээ!")
                else:
                    await context.send_activity(f"⚠️ Teams webhook илгээхэд алдаа гарлаа.")
                
                # Send rejection message to the original requester
                rejection_message = (
                    f"❌ **Таны чөлөөний хүсэлт ТАТГАЛЗАГДЛАА!**\n\n"
                    f"📅 Хүссэн хугацаа: {start_date} - {end_date}\n"
                    f"⏰ Цагийн хэмжээ: {hours}\n"
                    f"📝 Шалтгаан: {reason}\n\n"
                    f"💬 Дэлгэрэнгүй мэдээлэл авахыг хүсвэл менежертэйгээ холбогдоно уу."
                )
                
                success = await send_proactive_message(user_email, rejection_message)
                if success:
                    await context.send_activity(f"📢 {user_email} руу татгалзсан мэдэгдэл хүргэгдлээ.")
                else:
                    await context.send_activity(f"😅 {user_email} руу шууд мэдэгдэл илгээхэд асуудал гарлаа.")
                
        return True
        
    except Exception as e:
        print(f"Error handling action: {e}")
        await context.send_activity("😅 Уучлаарай, ямар нэгэн асуудал гарлаа. Дахин оролдоод үзээрэй.")
        return True

# OAuth event handler removed - using direct API calls instead

# Welcome and task checking functionality integrated into the AI responses
# The bot will now check for incomplete tasks and provide leave request assistance