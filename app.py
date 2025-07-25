import os
import logging
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import openai
from dotenv import load_dotenv
import asyncio
from msgraph import GraphServiceClient
from azure.identity.aio import ClientSecretCredential
import requests

# Logging тохиргоо
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

# Bot Framework тохиргоо
app_id = os.getenv("MICROSOFT_APP_ID", "")
app_password = os.getenv("MICROSOFT_APP_PASSWORD", "")

# Microsoft Graph тохиргоо
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

logger.info(f"Bot starting with App ID: {app_id[:10]}..." if app_id else "No App ID")

SETTINGS = BotFrameworkAdapterSettings(app_id, app_password)
ADAPTER = BotFrameworkAdapter(SETTINGS)

app = Flask(__name__)

async def send_manager_notification(user_email, leave_request_text, gpt_analysis=None):
    """Менежер рүү leave хүсэлтийн мэдэгдэл илгээх функц"""
    logger.info(f"Sending manager notification for user: {user_email}")
    
    credential = ClientSecretCredential(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )

    try:
        # GraphServiceClient үүсгэх
        graph_client = GraphServiceClient(credentials=credential, scopes=["https://graph.microsoft.com/.default"])

        # Менежерийн мэдээлэл авах
        result = await graph_client.users.by_user_id(user_email).manager.get()
        
        if result:
            manager_upn = result.user_principal_name
            manager_name = result.display_name or manager_upn
            logger.info(f"Found manager: {manager_name} ({manager_upn})")
            
            # Токен авах (шинэ credential үүсгэх)
            token_credential = ClientSecretCredential(
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )
            
            try:
                access_token = await token_credential.get_token("https://graph.microsoft.com/.default")
                headers = {
                    "Authorization": f"Bearer {access_token.token}",
                    "Content-Type": "application/json"
                }

                # Байгаа чатуудыг хайж олох оролдлого
                logger.info("Looking for existing chats with manager...")
                
                # 1. Хэрэглэгчийн чатуудыг авах
                chats_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/chats"
                chats_response = requests.get(chats_url, headers=headers)
                
                chat_id = None
                
                if chats_response.status_code == 200:
                    chats_data = chats_response.json()
                    logger.info(f"Found {len(chats_data.get('value', []))} chats")
                    
                    # Менежертэй 1:1 чат хайх
                    for chat in chats_data.get('value', []):
                        if chat.get('chatType') == 'oneOnOne':
                            # Чатын гишүүдийг шалгах
                            members_url = f"https://graph.microsoft.com/v1.0/chats/{chat['id']}/members"
                            members_response = requests.get(members_url, headers=headers)
                            
                            if members_response.status_code == 200:
                                members = members_response.json().get('value', [])
                                for member in members:
                                    if member.get('email') == manager_upn or member.get('userId') == result.id:
                                        chat_id = chat['id']
                                        logger.info(f"Found existing chat with manager: {chat_id}")
                                        break
                            if chat_id:
                                break
                
                # 2. Хэрэв байгаа чат олдоогүй бол шинэ чат үүсгэх оролдлого
                if not chat_id:
                    logger.info("No existing chat found, attempting to create new chat...")
                    
                    chat_url = "https://graph.microsoft.com/v1.0/chats"
                    chat_data = {
                        "chatType": "oneOnOne",
                        "members": [
                            {
                                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                                "roles": ["owner"],
                                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{manager_upn}')"
                            },
                            {
                                "@odata.type": "#microsoft.graph.aadUserConversationMember", 
                                "roles": ["owner"],
                                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user_email}')"
                            }
                        ]
                    }
                    
                    chat_response = requests.post(chat_url, headers=headers, json=chat_data)
                    
                    if chat_response.status_code == 201:
                        chat_id = chat_response.json()["id"]
                        logger.info(f"Created new chat: {chat_id}")
                    else:
                        logger.error(f"Chat creation failed: {chat_response.status_code}")
                        logger.error(chat_response.text)
                        return f"Чат үүсгэхэд алдаа: {chat_response.status_code}. Admin-аас Chat.Create permission хүсээрэй."
                
                # 3. Чатрүү Adaptive Card илгээх
                if chat_id:
                    # GPT анализын мэдээллийг Adaptive Card-д нэмэх
                    card_body = [
                        {
                            "type": "TextBlock",
                            "text": "🏖️ **Leave хүсэлт**",
                            "weight": "Bolder",
                            "size": "Medium"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Хэрэглэгч:** {user_email}",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Хүсэлт:** {leave_request_text}",
                            "wrap": True
                        }
                    ]
                    
                    # Хэрэв GPT анализ байгаа бол нэмэлт мэдээлэл нэмэх
                    if gpt_analysis:
                        card_body.extend([
                            {
                                "type": "TextBlock",
                                "text": f"**Төрөл:** {gpt_analysis.get('leave_type', 'тодорхойгүй')}",
                                "wrap": True
                            },
                            {
                                "type": "TextBlock", 
                                "text": f"**Хугацаа:** {gpt_analysis.get('duration', 'тодорхойгүй')}",
                                "wrap": True
                            },
                            {
                                "type": "TextBlock",
                                "text": f"**Шалтгаан:** {gpt_analysis.get('reason', 'тодорхойгүй')}",
                                "wrap": True
                            },
                            {
                                "type": "TextBlock",
                                "text": f"**Яаралтай байдал:** {gpt_analysis.get('urgency', 'ердийн')}",
                                "wrap": True
                            }
                        ])
                    
                    card_body.extend([
                        {
                            "type": "TextBlock",
                            "text": f"**Огноо:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": "Та энэ хүсэлтийг зөвшөөрөх үү?",
                            "wrap": True
                        }
                    ])

                    adaptive_card_content = {
                        "type": "AdaptiveCard",
                        "body": card_body,
                        "actions": [
                            {
                                "type": "Action.Submit",
                                "title": "✅ Зөвшөөрөх",
                                "data": {"action": "approve", "user_email": user_email}
                            },
                            {
                                "type": "Action.Submit",
                                "title": "❌ Татгалзах", 
                                "data": {"action": "reject", "user_email": user_email}
                            }
                        ],
                        "version": "1.4"
                    }

                    message_url = f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages"
                    message_data = {
                        "body": {
                            "contentType": "html",
                            "content": "Leave хүсэлтийн шийдвэр"
                        },
                        "attachments": [
                            {
                                "contentType": "application/vnd.microsoft.card.adaptive",
                                "content": adaptive_card_content
                            }
                        ]
                    }
                    
                    logger.info("Sending Adaptive Card to chat...")
                    message_response = requests.post(message_url, headers=headers, json=message_data)
                    
                    if message_response.status_code == 201:
                        logger.info("Adaptive Card sent successfully!")
                        return f"Таны leave хүсэлтийг {manager_name} менежер рүү Teams чатаар илгээлээ. ✅"
                    else:
                        logger.error(f"Message send error: {message_response.status_code}")
                        logger.error(message_response.text)
                        return "Teams мессеж илгээхэд алдаа гарлаа."
                else:
                    return "Teams чат олдсонгүй эсвэл үүсгэж чадсангүй."
                    
            finally:
                await token_credential.close()
        else:
            logger.warning("Manager not found")
            return "Таны менежер олдсонгүй."
            
    except Exception as e:
        logger.error(f"Error in send_manager_notification: {str(e)}")
        return f"Алдаа гарлаа: {str(e)}"
    finally:
        await credential.close()

async def analyze_leave_request_with_gpt(text):
    """GPT-4 ашиглан leave хүсэлтийг ойлгох функц"""
    if not text or not openai.api_key:
        return None
    
    try:
        client = openai.OpenAI(api_key=openai.api_key)
        
        prompt = f"""
        Та хүний мэдрэмжтэй AI туслач юм. Дараах текстийг уншиж, энэ нь ажлаас чөлөө авах хүсэлт эсэхийг тодорхойлно уу.

        Текст: "{text}"

        Хэрэв энэ нь чөлөө авах хүсэлт бол JSON форматаар дараах мэдээллийг өгнө үү:
        {{
            "is_leave_request": true,
            "leave_type": "амралт/өвчтэй/хувийн/гэр бүлийн/бусад",
            "duration": "1 өдөр/хэдэн өдөр/тодорхойгүй",
            "reason": "шалтгааны товч тайлбар",
            "urgency": "яаралтай/ердийн/тодорхойгүй",
            "processed_request": "Formal хэлбэрээр боловсруулсан хүсэлт"
        }}

        Хэрэв чөлөө авах хүсэлт биш бол:
        {{
            "is_leave_request": false
        }}

        Монгол хэл, транслит, англи хэлээр бичсэн хүсэлтийг бүгдийг ойлгоно уу.
        """
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # JSON parse хийх
        import json
        try:
            result = json.loads(result_text)
            return result
        except json.JSONDecodeError:
            # Хэрэв JSON биш бол text-ээс is_leave_request-г хайх
            if "true" in result_text.lower() and "leave" in result_text.lower():
                return {
                    "is_leave_request": True,
                    "leave_type": "тодорхойгүй",
                    "duration": "тодорхойгүй", 
                    "reason": text,
                    "urgency": "ердийн",
                    "processed_request": text
                }
            return {"is_leave_request": False}
            
    except Exception as e:
        logger.error(f"GPT analysis error: {str(e)}")
        return None

def is_leave_request(text):
    """Leave хүсэлт эсэхийг шалгах функц (fallback)"""
    if not text:
        return False
        
    leave_keywords = [
        'чөлөө', 'chuluu', 'leave', 'амрах', 'амралт',
        'өвчтэй', 'ovchtei', 'sick', 'эмнэлэг', 'emnelg',
        'хүсэлт', 'huselt', 'request', 'зөвшөөрөл', 'zuvshuurul'
    ]
    
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in leave_keywords)

# Энгийн health check endpoint
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server is running",
        "endpoints": ["/api/messages"],
        "app_id_configured": bool(os.getenv("MICROSOFT_APP_ID")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "graph_configured": bool(TENANT_ID and CLIENT_ID and CLIENT_SECRET)
    })

@app.route("/api/messages", methods=["POST"])
def process_messages():
    try:
        logger.info("Received message request")
        
        # Request body шалгах
        if not request.is_json:
            logger.error("Request is not JSON")
            return jsonify({"error": "Content-Type must be application/json"}), 400
            
        body = request.get_json()
        logger.info(f"Request body: {body}")
        
        # Хэрэв body хоосон бол
        if not body:
            logger.error("Empty request body")
            return jsonify({"error": "Request body is required"}), 400

        # Activity объект үүсгэх
        try:
            activity = Activity().deserialize(body)
            logger.info(f"Activity type: {activity.type}, text: {activity.text}")
        except Exception as e:
            logger.error(f"Failed to deserialize activity: {str(e)}")
            return jsonify({"error": f"Invalid activity format: {str(e)}"}), 400

        async def logic(context: TurnContext):
            try:
                if activity.type == "message":
                    user_text = activity.text or "No text provided"
                    user_email = activity.from_property.aad_object_id if hasattr(activity.from_property, 'aad_object_id') else None
                    user_name = activity.from_property.name if hasattr(activity.from_property, 'name') else "Unknown User"
                    
                    logger.info(f"Processing message from {user_name}: {user_text}")
                    
                    # GPT-4 ашиглан leave хүсэлтийг анализ хийх
                    await context.send_activity("🤖 Таны мессежийг анализ хийж байна...")
                    
                    gpt_analysis = await analyze_leave_request_with_gpt(user_text)
                    
                    if gpt_analysis and gpt_analysis.get("is_leave_request"):
                        logger.info("Leave request detected by GPT-4!")
                        
                        # GPT-4-ээс ирсэн мэдээллийг ашиглах
                        leave_type = gpt_analysis.get("leave_type", "тодорхойгүй")
                        duration = gpt_analysis.get("duration", "тодорхойгүй")
                        reason = gpt_analysis.get("reason", user_text)
                        urgency = gpt_analysis.get("urgency", "ердийн")
                        processed_request = gpt_analysis.get("processed_request", user_text)
                        
                        # Дэлгэрэнгүй мэдээлэл харуулах
                        analysis_message = f"""
✅ **Leave хүсэлт таныгдлаа!**

📋 **Анализын дүн:**
• **Төрөл:** {leave_type}
• **Хугацаа:** {duration}  
• **Шалтгаан:** {reason}
• **Яаралтай байдал:** {urgency}

🚀 Менежер рүү илгээж байна...
                        """
                        await context.send_activity(analysis_message.strip())
                        
                        # Хэрэв user email байхгүй бол default ашиглах
                        if not user_email:
                            # Teams-аас user email авах оролдлого
                            user_email = getattr(activity.from_property, 'email', None) or "tuvshinjargal@fibo.cloud"
                        
                        try:
                            # Менежер рүү дэлгэрэнгүй мэдэгдэл илгээх
                            result = await send_manager_notification(user_email, processed_request, gpt_analysis)
                            await context.send_activity(result)
                        except Exception as e:
                            logger.error(f"Manager notification error: {str(e)}")
                            await context.send_activity(f"Менежер рүү мэдэгдэл илгээхэд алдаа: {str(e)}")
                        
                        return
                    elif gpt_analysis is None:
                        # GPT analysis амжилтгүй болсон тохиолдолд fallback ашиглах
                        logger.warning("GPT analysis failed, using fallback method")
                        if is_leave_request(user_text):
                            logger.info("Leave request detected by fallback method!")
                            await context.send_activity("🏖️ Leave хүсэлт хүлээн авлаа. Менежер рүү илгээж байна...")
                            
                            # Хэрэв user email байхгүй бол default ашиглах
                            if not user_email:
                                user_email = getattr(activity.from_property, 'email', None) or "tuvshinjargal@fibo.cloud"
                            
                            try:
                                # Менежер рүү мэдэгдэл илгээх
                                result = await send_manager_notification(user_email, user_text)
                                await context.send_activity(result)
                            except Exception as e:
                                logger.error(f"Manager notification error: {str(e)}")
                                await context.send_activity(f"Менежер рүү мэдэгдэл илгээхэд алдаа: {str(e)}")
                            
                            return
                    
                    # Хэрэв leave хүсэлт биш бол OpenAI ашиглах
                    if not openai.api_key:
                        logger.warning("OpenAI API key not configured")
                        await context.send_activity("OpenAI API key тохируулаагүй байна.")
                        return
                    
                    try:
                        # OpenAI API дуудах
                        client = openai.OpenAI(api_key=openai.api_key)
                        response = client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=[{"role": "user", "content": user_text}]
                        )
                        
                        ai_response = response.choices[0].message.content
                        logger.info(f"OpenAI response: {ai_response[:100]}...")
                        await context.send_activity(ai_response)
                        
                    except Exception as e:
                        logger.error(f"OpenAI API error: {str(e)}")
                        await context.send_activity(f"OpenAI API алдаа: {str(e)}")
                        
                else:
                    logger.info(f"Non-message activity type: {activity.type}")
                    
            except Exception as e:
                logger.error(f"Error in logic function: {str(e)}")
                await context.send_activity(f"Серверийн алдаа: {str(e)}")

        # Bot adapter ашиглан мессеж боловсруулах
        try:
            auth_header = request.headers.get('Authorization', '')
            logger.info(f"Auth header present: {bool(auth_header)}")
            
            # Async function-ийг sync контекстэд ажиллуулах
            asyncio.run(ADAPTER.process_activity(activity, auth_header, logic))
            logger.info("Message processed successfully")
            return jsonify({"status": "success"}), 200
            
        except Exception as e:
            logger.error(f"Adapter processing error: {str(e)}")
            return jsonify({"error": f"Bot framework error: {str(e)}"}), 500
            
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# Error handler
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)