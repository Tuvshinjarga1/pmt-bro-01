import os
import logging
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import asyncio
import json
from botbuilder.schema import ConversationReference
import re
from datetime import datetime
import uuid

# Logging тохиргоо
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

for directory in [CONVERSATION_DIR, LEAVE_REQUESTS_DIR]:
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
            "conversation_reference": reference.serialize()
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
                            "channel_id": user_info.get("channel_id")
                        })
                    else:
                        # Хуучин формат - зөвхөн user_id нэмэх
                        users.append({
                            "user_id": user_id,
                            "email": None,
                            "user_name": None,
                            "last_activity": None,
                            "channel_id": None
                        })
                else:
                    users.append({
                        "user_id": user_id,
                        "email": None,
                        "user_name": None,
                        "last_activity": None,
                        "channel_id": None
                    })
        return users
    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}")
        return []

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server is running",
        "endpoints": ["/api/messages", "/proactive-message", "/users", "/broadcast", "/leave-request", "/approval-callback"],
        "app_id_configured": bool(os.getenv("MICROSOFT_APP_ID")),
        "stored_users": len(list_all_users())
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
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "approver_email": APPROVER_EMAIL,
            "approver_user_id": APPROVER_USER_ID
        }

        # Хүсэлт хадгалах
        if not save_leave_request(request_data):
            return jsonify({"error": "Failed to save leave request"}), 500

        # Approval card үүсгэх
        approval_card = create_approval_card(request_data)

        # Approver руу adaptive card илгээх
        approver_conversation = load_conversation_reference(APPROVER_USER_ID)
        if not approver_conversation:
            return jsonify({"error": "Approver conversation reference not found"}), 404

        async def send_approval_card(context: TurnContext):
            await context.send_activity({
                "type": "message",
                "text": f"Шинэ чөлөөний хүсэлт: {requester_info.get('user_name', requester_email)}",
                "attachments": [{
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": approval_card
                }]
            })

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
                        logger.info(f"Processing message from user {user_id}: {user_text}")
                        await context.send_activity(f"Таны мессежийг хүлээн авлаа: {user_text}")
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

        # Approval status шинэчлэх
        if action == "approve":
            request_data["status"] = "approved"
            request_data["approved_at"] = datetime.now().isoformat()
            request_data["approved_by"] = context.activity.from_property.id
            
            # Хүсэлт хадгалах
            save_leave_request(request_data)
            
            # Approver руу баталгаажуулах
            await context.send_activity(f"✅ Чөлөөний хүсэлт зөвшөөрөгдлөө!\n👤 {request_data['requester_name']}\n📅 {request_data['start_date']} - {request_data['end_date']}")
            
            # Хүсэлт гаргагч руу мэдэгдэх
            requester_conversation = load_conversation_reference(request_data["requester_user_id"])
            if requester_conversation:
                async def notify_approval(ctx: TurnContext):
                    await ctx.send_activity(f"🎉 Таны чөлөөний хүсэлт зөвшөөрөгдлөө!\n📅 {request_data['start_date']} - {request_data['end_date']} ({request_data['days']} хоног)\n✨ Сайхан амралтаа!")

                asyncio.run(
                    ADAPTER.continue_conversation(
                        requester_conversation,
                        notify_approval,
                        app_id
                    )
                )
            
        elif action == "reject":
            request_data["status"] = "rejected"
            request_data["rejected_at"] = datetime.now().isoformat()
            request_data["rejected_by"] = context.activity.from_property.id
            
            # Хүсэлт хадгалах
            save_leave_request(request_data)
            
            # Approver руу баталгаажуулах
            await context.send_activity(f"❌ Чөлөөний хүсэлт татгалзагдлаа\n👤 {request_data['requester_name']}\n📅 {request_data['start_date']} - {request_data['end_date']}")
            
            # Хүсэлт гаргагч руу мэдэгдэх
            requester_conversation = load_conversation_reference(request_data["requester_user_id"])
            if requester_conversation:
                async def notify_rejection(ctx: TurnContext):
                    await ctx.send_activity(f"❌ Таны чөлөөний хүсэлт татгалзагдлаа\n📅 {request_data['start_date']} - {request_data['end_date']} ({request_data['days']} хоног)\n💬 Нэмэлт мэдээллийн хэрэгтэй бол удирдлагатайгаа ярилцана уу.")

                asyncio.run(
                    ADAPTER.continue_conversation(
                        requester_conversation,
                        notify_rejection,
                        app_id
                    )
                )

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)