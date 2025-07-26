import os
import logging
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import asyncio
import json
from botbuilder.schema import ConversationReference
from datetime import datetime, timedelta
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
USER_PROFILES_DIR = "user_profiles"
LEAVE_REQUESTS_DIR = "leave_requests"

for directory in [CONVERSATION_DIR, USER_PROFILES_DIR, LEAVE_REQUESTS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

def save_conversation_reference(activity):
    """Хэрэглэгчийн conversation reference-г хадгалах функц"""
    try:
        reference = TurnContext.get_conversation_reference(activity)
        user_id = activity.from_property.id if activity.from_property else "unknown"
        conversation_id = activity.conversation.id if activity.conversation else "unknown"
        
        # Хэрэглэгчийн ID-ээр файлын нэр үүсгэх (special characters-ээс зайлсхийх)
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(reference.serialize(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved conversation reference for user {user_id} to {filename}")
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
            ref_data = json.load(f)
        return ConversationReference().deserialize(ref_data)
    except Exception as e:
        logger.error(f"Failed to load conversation reference for user {user_id}: {str(e)}")
        return None

def save_user_profile(user_id, profile_data):
    """Хэрэглэгчийн профайл мэдээллийг хадгалах"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{USER_PROFILES_DIR}/profile_{safe_user_id}.json"
        
        # Одоогийн цаг болон профайл мэдээллийг нэмэх
        profile_data.update({
            "user_id": user_id,
            "last_updated": datetime.now().isoformat(),
            "created_at": profile_data.get("created_at", datetime.now().isoformat())
        })
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved user profile for {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save user profile: {str(e)}")
        return False

def load_user_profile(user_id):
    """Хэрэглэгчийн профайл мэдээллийг унших"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{USER_PROFILES_DIR}/profile_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load user profile: {str(e)}")
        return None

def create_leave_request(user_id, leave_data):
    """Чөлөөний хүсэлт үүсгэх"""
    try:
        request_id = str(uuid.uuid4())
        leave_request = {
            "request_id": request_id,
            "user_id": user_id,
            "start_date": leave_data.get("start_date"),
            "end_date": leave_data.get("end_date"),
            "reason": leave_data.get("reason", ""),
            "leave_type": leave_data.get("leave_type", "амралт"),
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "approved_at": None,
            "approved_by": None,
            "comments": []
        }
        
        filename = f"{LEAVE_REQUESTS_DIR}/request_{request_id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(leave_request, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Created leave request {request_id} for user {user_id}")
        return leave_request
    except Exception as e:
        logger.error(f"Failed to create leave request: {str(e)}")
        return None

def load_leave_request(request_id):
    """Чөлөөний хүсэлтийн мэдээлэл унших"""
    try:
        filename = f"{LEAVE_REQUESTS_DIR}/request_{request_id}.json"
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load leave request: {str(e)}")
        return None

def update_leave_request_status(request_id, status, approved_by=None, comments=None):
    """Чөлөөний хүсэлтийн статус шинэчлэх"""
    try:
        leave_request = load_leave_request(request_id)
        if not leave_request:
            return False
        
        leave_request["status"] = status
        if status == "approved" or status == "rejected":
            leave_request["approved_at"] = datetime.now().isoformat()
            leave_request["approved_by"] = approved_by
        
        if comments:
            leave_request["comments"].append({
                "comment": comments,
                "timestamp": datetime.now().isoformat(),
                "by": approved_by
            })
        
        filename = f"{LEAVE_REQUESTS_DIR}/request_{request_id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(leave_request, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        logger.error(f"Failed to update leave request: {str(e)}")
        return False

def get_user_leave_requests(user_id):
    """Хэрэглэгчийн бүх чөлөөний хүсэлт"""
    try:
        requests = []
        for filename in os.listdir(LEAVE_REQUESTS_DIR):
            if filename.startswith("request_") and filename.endswith(".json"):
                with open(f"{LEAVE_REQUESTS_DIR}/{filename}", "r", encoding="utf-8") as f:
                    request_data = json.load(f)
                    if request_data.get("user_id") == user_id:
                        requests.append(request_data)
        return sorted(requests, key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.error(f"Failed to get user leave requests: {str(e)}")
        return []

def get_pending_requests_for_manager(manager_id):
    """Manager-д хүлээгдэж байгаа хүсэлтүүд"""
    try:
        pending_requests = []
        
        # Бүх хэрэглэгчийн профайлыг шалгаж, тухайн manager-тай хэрэглэгчдийг олох
        for filename in os.listdir(USER_PROFILES_DIR):
            if filename.startswith("profile_") and filename.endswith(".json"):
                with open(f"{USER_PROFILES_DIR}/{filename}", "r", encoding="utf-8") as f:
                    profile = json.load(f)
                    if profile.get("manager_id") == manager_id:
                        user_requests = get_user_leave_requests(profile["user_id"])
                        for req in user_requests:
                            if req["status"] == "pending":
                                req["user_profile"] = profile
                                pending_requests.append(req)
        
        return sorted(pending_requests, key=lambda x: x["created_at"])
    except Exception as e:
        logger.error(f"Failed to get pending requests for manager: {str(e)}")
        return []

def list_all_users():
    """Хадгалагдсан бүх хэрэглэгчийн жагсаалт гаргах"""
    try:
        users = []
        for filename in os.listdir(CONVERSATION_DIR):
            if filename.startswith("user_") and filename.endswith(".json"):
                user_id = filename[5:-5].replace("_", ":")  # user_ prefix болон .json suffix арилгах
                users.append(user_id)
        return users
    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}")
        return []

async def send_notification_to_user(user_id, message):
    """Хэрэглэгч рүү мэдэгдэл илгээх"""
    try:
        conversation_reference = load_conversation_reference(user_id)
        if conversation_reference:
            async def send_proactive(context: TurnContext):
                await context.send_activity(message)
            
            await ADAPTER.continue_conversation(
                conversation_reference,
                send_proactive,
                app_id
            )
            logger.info(f"Notification sent to user {user_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to send notification to user {user_id}: {str(e)}")
    return False

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server with Leave Management is running",
        "endpoints": ["/api/messages", "/proactive-message", "/users", "/profile", "/leave-request", "/approve-leave", "/my-requests"],
        "app_id_configured": bool(os.getenv("MICROSOFT_APP_ID")),
        "stored_users": len(list_all_users())
    })

@app.route("/users", methods=["GET"])
def get_users():
    """Хадгалагдсан хэрэглэгчдийн жагсаалт"""
    users = list_all_users()
    return jsonify({"users": users, "count": len(users)})

@app.route("/profile", methods=["POST"])
def save_profile():
    """Хэрэглэгчийн профайл хадгалах"""
    data = request.json
    user_id = data.get("user_id")
    
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    
    profile_data = {
        "name": data.get("name"),
        "position": data.get("position"),
        "department": data.get("department"),
        "manager_id": data.get("manager_id"),
        "manager_name": data.get("manager_name"),
        "email": data.get("email"),
        "phone": data.get("phone")
    }
    
    if save_user_profile(user_id, profile_data):
        return jsonify({"status": "success", "message": "Профайл амжилттай хадгалагдлаа"})
    else:
        return jsonify({"error": "Failed to save profile"}), 500

@app.route("/profile/<user_id>", methods=["GET"])
def get_profile(user_id):
    """Хэрэглэгчийн профайл харах"""
    profile = load_user_profile(user_id)
    if profile:
        return jsonify(profile)
    else:
        return jsonify({"error": "Profile not found"}), 404

@app.route("/leave-request", methods=["POST"])
def submit_leave_request():
    """Чөлөөний хүсэлт илгээх"""
    data = request.json
    user_id = data.get("user_id")
    
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    
    # Хэрэглэгчийн профайл шалгах
    profile = load_user_profile(user_id)
    if not profile:
        return jsonify({"error": "User profile not found. Please set up your profile first."}), 404
    
    leave_data = {
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "reason": data.get("reason", ""),
        "leave_type": data.get("leave_type", "амралт")
    }
    
    # Шаардлагатай талбарууд шалгах
    if not leave_data["start_date"] or not leave_data["end_date"]:
        return jsonify({"error": "start_date and end_date are required"}), 400
    
    leave_request = create_leave_request(user_id, leave_data)
    if leave_request:
        # Manager-д мэдэгдэл илгээх
        if profile.get("manager_id"):
            manager_message = f"""
🔔 Шинэ чөлөөний хүсэлт ирлээ

👤 Ажилтан: {profile.get('name', user_id)}
🏢 Албан тушаал: {profile.get('position', 'Тодорхойгүй')}
📅 Эхлэх огноо: {leave_data['start_date']}
📅 Дуусах огноо: {leave_data['end_date']}
📝 Шалтгаан: {leave_data['reason']}
🏷️ Төрөл: {leave_data['leave_type']}

Зөвшөөрөх: /approve {leave_request['request_id']}
Татгалзах: /reject {leave_request['request_id']}
            """
            asyncio.create_task(send_notification_to_user(profile["manager_id"], manager_message.strip()))
        
        return jsonify({
            "status": "success", 
            "message": "Чөлөөний хүсэлт илгээгдлээ",
            "request_id": leave_request["request_id"]
        })
    else:
        return jsonify({"error": "Failed to create leave request"}), 500

@app.route("/approve-leave", methods=["POST"])
def approve_leave():
    """Чөлөөний хүсэлт зөвшөөрөх/татгалзах"""
    data = request.json
    request_id = data.get("request_id")
    action = data.get("action")  # "approve" эсвэл "reject"
    approved_by = data.get("approved_by")
    comments = data.get("comments", "")
    
    if not all([request_id, action, approved_by]):
        return jsonify({"error": "request_id, action, and approved_by are required"}), 400
    
    if action not in ["approve", "reject"]:
        return jsonify({"error": "action must be 'approve' or 'reject'"}), 400
    
    leave_request = load_leave_request(request_id)
    if not leave_request:
        return jsonify({"error": "Leave request not found"}), 404
    
    status = "approved" if action == "approve" else "rejected"
    if update_leave_request_status(request_id, status, approved_by, comments):
        # Хэрэглэгчдэд мэдэгдэх
        user_profile = load_user_profile(leave_request["user_id"])
        status_text = "зөвшөөрөгдлөө ✅" if action == "approve" else "татгалзагдлаа ❌"
        
        user_message = f"""
📋 Таны чөлөөний хүсэлт {status_text}

📅 Огноо: {leave_request['start_date']} - {leave_request['end_date']}
📝 Шалтгаан: {leave_request['reason']}
👤 Зөвшөөрсөн: {approved_by}
💬 Тайлбар: {comments if comments else 'Байхгүй'}
        """
        
        asyncio.create_task(send_notification_to_user(leave_request["user_id"], user_message.strip()))
        
        return jsonify({
            "status": "success", 
            "message": f"Хүсэлт {status_text}",
            "request": leave_request
        })
    else:
        return jsonify({"error": "Failed to update leave request"}), 500

@app.route("/my-requests/<user_id>", methods=["GET"])
def get_my_requests(user_id):
    """Хэрэглэгчийн чөлөөний хүсэлтүүд"""
    requests = get_user_leave_requests(user_id)
    return jsonify({"requests": requests, "count": len(requests)})

@app.route("/pending-requests/<manager_id>", methods=["GET"])
def get_pending_requests(manager_id):
    """Manager-ийн хүлээгдэж байгаа хүсэлтүүд"""
    requests = get_pending_requests_for_manager(manager_id)
    return jsonify({"pending_requests": requests, "count": len(requests)})

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
                    user_text = activity.text or "No text provided"
                    user_id = activity.from_property.id if activity.from_property else "unknown"
                    logger.info(f"Processing message from user {user_id}: {user_text}")
                    
                    # Команд боловсруулах
                    if user_text.startswith("/approve "):
                        request_id = user_text.split(" ", 1)[1]
                        leave_request = load_leave_request(request_id)
                        if leave_request:
                            if update_leave_request_status(request_id, "approved", user_id):
                                await context.send_activity(f"✅ Хүсэлт зөвшөөрөгдлөө: {request_id}")
                                # Хэрэглэгчдэд мэдэгдэх
                                user_message = f"🎉 Таны чөлөөний хүсэлт зөвшөөрөгдлөө!\nОгноо: {leave_request['start_date']} - {leave_request['end_date']}"
                                asyncio.create_task(send_notification_to_user(leave_request["user_id"], user_message))
                            else:
                                await context.send_activity("❌ Хүсэлт зөвшөөрөхөд алдаа гарлаа")
                        else:
                            await context.send_activity("❌ Хүсэлт олдсонгүй")
                    
                    elif user_text.startswith("/reject "):
                        request_id = user_text.split(" ", 1)[1]
                        leave_request = load_leave_request(request_id)
                        if leave_request:
                            if update_leave_request_status(request_id, "rejected", user_id):
                                await context.send_activity(f"❌ Хүсэлт татгалзагдлаа: {request_id}")
                                # Хэрэглэгчдэд мэдэгдэх
                                user_message = f"😔 Таны чөлөөний хүсэлт татгалзагдлаа.\nОгноо: {leave_request['start_date']} - {leave_request['end_date']}"
                                asyncio.create_task(send_notification_to_user(leave_request["user_id"], user_message))
                            else:
                                await context.send_activity("❌ Хүсэлт татгалзахад алдаа гарлаа")
                        else:
                            await context.send_activity("❌ Хүсэлт олдсонгүй")
                    
                    elif user_text.lower() in ["/help", "тусламж"]:
                        help_text = """
🤖 Чөлөөний хүсэлт менежментийн бот

📋 Боломжит командууд:
• /approve [request_id] - Хүсэлт зөвшөөрөх
• /reject [request_id] - Хүсэлт татгалзах
• /help - Энэ тусламж

🌐 API endpoints:
• POST /profile - Профайл тохируулах
• GET /profile/{user_id} - Профайл харах
• POST /leave-request - Чөлөөний хүсэлт илгээх
• GET /my-requests/{user_id} - Миний хүсэлтүүд
• GET /pending-requests/{manager_id} - Хүлээгдэж байгаа хүсэлтүүд
                        """
                        await context.send_activity(help_text.strip())
                    
                    else:
                        # Хэрэглэгчийн профайл шалгах
                        profile = load_user_profile(user_id)
                        if profile:
                            await context.send_activity(f"Сайн байна уу {profile.get('name', user_id)}! Таны мессежийг хүлээн авлаа: {user_text}")
                        else:
                            await context.send_activity(f"""
Сайн байна уу! Таны мессежийг хүлээн авлаа: {user_text}

⚠️ Та профайлаа тохируулаагүй байна. Чөлөөний хүсэлт илгээхийн тулд эхлээд профайлаа тохируулна уу.

POST /profile endpoint ашиглан профайл үүсгэх боломжтой.
                            """)
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
    for user_id in users:
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
                results.append({"user_id": user_id, "status": "success"})
                logger.info(f"Message sent to user {user_id}")
            else:
                results.append({"user_id": user_id, "status": "failed", "error": "Reference not found"})
        except Exception as e:
            results.append({"user_id": user_id, "status": "failed", "error": str(e)})
            logger.error(f"Failed to send message to user {user_id}: {str(e)}")
    
    return jsonify({"results": results, "total_users": len(users), "message": message_text}), 200

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)