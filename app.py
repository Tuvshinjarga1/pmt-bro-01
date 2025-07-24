import os
import logging
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import openai
from dotenv import load_dotenv
import asyncio
# Planner service нэмж байна
from planner_service import PlannerService
# Leave request, Teams messaging болон Organization services
from leave_request_service import LeaveRequestService
from teams_auth_service import TeamsAuthService
from organization_service import OrganizationService
from approval_handler import ApprovalHandler

# Logging тохиргоо
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

# Bot Framework тохиргоо
app_id = os.getenv("MICROSOFT_APP_ID", "")
app_password = os.getenv("MICROSOFT_APP_PASSWORD", "")

logger.info(f"Bot starting with App ID: {app_id[:10]}..." if app_id else "No App ID")

SETTINGS = BotFrameworkAdapterSettings(app_id, app_password)
ADAPTER = BotFrameworkAdapter(SETTINGS)

app = Flask(__name__)

# Энгийн health check endpoint
@app.route("/", methods=["GET"])
def health_check():
    try:
        # Services-ийг шалгах
        from config import Config
        config = Config()
        
        # Planner service шалгах
        planner_ready = bool(config.GRAPH_TENANT_ID and config.GRAPH_CLIENT_ID and config.GRAPH_CLIENT_SECRET)
        
        # Teams service шалгах 
        teams_ready = bool(config.TEAMS_WEBHOOK_URL)
        
        # OpenAI service шалгах
        openai_ready = bool(config.OPENAI_API_KEY)
        
        return jsonify({
            "status": "running",
            "message": "Flask Bot Server is running",
            "endpoints": ["/api/messages"],
            "services": {
                "bot_framework": bool(os.getenv("MICROSOFT_APP_ID")),
                "openai": openai_ready,
                "planner": planner_ready,
                "teams_webhook": teams_ready
            },
            "version": "1.0.0"
        })
        
    except Exception as e:
        logger.error(f"Health check алдаа: {str(e)}")
        return jsonify({
            "status": "error", 
            "message": f"Health check алдаа: {str(e)}"
        }), 500

@app.route("/api/approval", methods=["POST"])
def handle_approval():
    """Лидэрийн зөвшөөрөл/татгалзал боловсруулах"""
    try:
        logger.info("Received approval request")
        
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400
            
        body = request.get_json()
        logger.info(f"Approval body: {body}")
        
        manager_email = body.get("manager_email")
        response_text = body.get("response_text")
        
        if not manager_email or not response_text:
            return jsonify({"error": "manager_email болон response_text шаардлагатай"}), 400
        
        # Approval handler ашиглах
        approval_handler = ApprovalHandler()
        success = approval_handler.process_manager_response(manager_email, response_text)
        
        if success:
            return jsonify({"status": "success", "message": "Хариулт амжилттай боловсруулагдлаа"}), 200
        else:
            return jsonify({"status": "error", "message": "Хариулт боловсруулахад алдаа гарлаа"}), 400
            
    except Exception as e:
        logger.error(f"Approval handling алдаа: {str(e)}")
        return jsonify({"error": f"Server алдаа: {str(e)}"}), 500

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
                    logger.info(f"Processing message: {user_text}")
                    
                    # Хэрэглэгчийн email хаяг олох (Teams-аас)
                    user_email = None
                    user_id = None
                    
                    try:
                        if activity.from_property:
                            # Teams-аас ирэх хэрэглэгчийн мэдээлэл
                            user_id = getattr(activity.from_property, 'id', None)
                            user_name = getattr(activity.from_property, 'name', None)
                            aad_object_id = getattr(activity.from_property, 'aad_object_id', None)
                            
                            # UPN (User Principal Name) эсвэл email авах оролдлого
                            if hasattr(activity.from_property, 'properties'):
                                properties = getattr(activity.from_property, 'properties', None)
                                if properties and isinstance(properties, dict):
                                    user_email = properties.get('upn') or properties.get('email')
                            
                            # Хэрэв email олдоогүй бол AAD object ID эсвэл name ашиглах
                            if not user_email:
                                user_email = aad_object_id or user_name or user_id
                        
                        logger.info(f"User info - ID: {user_id}, Email: {user_email}")
                    except Exception as e:
                        logger.error(f"Error getting user info: {str(e)}")
                        user_email = "unknown_user"
                    
                    # Чөлөөний хүсэлт эсэхийг эхлээд шалгах
                    is_leave_request = False
                    if user_email and user_email != "unknown_user":
                        try:
                            # Энгийн чөлөөний үг байгаа эсэхийг шалгах
                            leave_keywords = ['chuluu', 'чөлөө', 'амралт', 'өвчин', 'өвчтэй', 'гарах', 'хүсэлт']
                            user_text_lower = user_text.lower()
                            
                            for keyword in leave_keywords:
                                if keyword in user_text_lower:
                                    is_leave_request = True
                                    break
                            
                            logger.info(f"Possible leave request detected: {is_leave_request}")
                            
                        except Exception as e:
                            logger.error(f"Error checking for leave keywords: {str(e)}")
                    
                    # Зөвхөн чөлөөний хүсэлт биш үед planner tasks харуулах
                    if not is_leave_request and user_email and user_email != "unknown_user":
                        try:
                            logger.info(f"Getting planner tasks for user: {user_email}")
                            planner = PlannerService()
                            
                            # Planner сервис бэлэн эсэхийг шалгах
                            if not hasattr(planner, 'headers') or planner.headers is None:
                                logger.warning("Planner service тохируулаагүй байна")
                                await context.send_activity("⚠️ Planner service тохируулаагүй байна.\n\n---\n")
                            else:
                                # Planner болон personal tasks авах
                                planner_tasks = planner.get_user_incomplete_tasks(user_email) or []
                                personal_tasks = planner.get_personal_tasks(user_email) or []
                                
                                if planner_tasks or personal_tasks:
                                    tasks_message = planner.format_tasks_for_display(planner_tasks, personal_tasks)
                                    logger.info(f"Found {len(planner_tasks)} planner tasks and {len(personal_tasks)} personal tasks")
                                    
                                    # Эхлээд даалгавруудыг харуулах
                                    await context.send_activity(f"📋 **Таны дутуу даалгаврууд:**\n\n{tasks_message}\n\n---\n")
                                else:
                                    await context.send_activity("✅ Танд дутуу даалгавар алга байна! 🎉\n\n---\n")
                                
                        except Exception as e:
                            logger.error(f"Error getting planner tasks: {str(e)}")
                            await context.send_activity("⚠️ Даалгавар шалгахад алдаа гарлаа.\n\n---\n")
                    else:
                        if is_leave_request:
                            logger.info("Leave request detected, skipping planner tasks display")
                        else:
                            logger.info("No valid user email found, skipping planner tasks check")
                    
                    # Лидэрийн хариулт эсэхийг шалгах
                    approval_processed = False
                    if user_email and user_email != "unknown_user":
                        try:
                            # APPROVE/REJECT команд эсэхийг шалгах
                            if any(cmd in user_text.upper() for cmd in ['APPROVE', 'REJECT']):
                                logger.info("Manager approval/rejection command detected")
                                approval_handler = ApprovalHandler()
                                success = approval_handler.process_manager_response(user_email, user_text)
                                
                                if success:
                                    await context.send_activity("✅ Таны хариулт амжилттай боловсруулагдлаа.")
                                    approval_processed = True
                                else:
                                    help_msg = approval_handler.generate_help_message()
                                    await context.send_activity(f"❌ Командыг ойлгосонгүй.\n\n{help_msg}")
                                    approval_processed = True
                        except Exception as e:
                            logger.error(f"Error processing approval command: {str(e)}")
                    
                    # NLP ашиглан чөлөөний хүсэлт шалгах (approval биш үед)
                    leave_request_processed = False
                    if not approval_processed and user_email and user_email != "unknown_user":
                        try:
                            logger.info(f"Analyzing message for leave request: {user_text[:100]}...")
                            leave_service = LeaveRequestService()
                            
                            # Leave service готов эсэхийг шалгах
                            if not hasattr(leave_service, 'openai_key') or not leave_service.openai_key:
                                logger.warning("Leave service тохируулаагүй байна")
                                leave_analysis = None
                            else:
                                leave_analysis = leave_service.analyze_message_for_leave_request(user_text, user_email)
                            
                            if leave_analysis and leave_analysis.get("is_leave_request", False):
                                confidence = leave_analysis.get("confidence", 0.0)
                                missing_info = leave_analysis.get("missing_info", [])
                                logger.info(f"Leave request detected with confidence: {confidence}, missing: {missing_info}")
                                
                                # Хэрэв мэдээлэл дутуу бол лавлах
                                if missing_info:
                                    follow_up = leave_service.generate_follow_up_questions(missing_info)
                                    await context.send_activity(
                                        f"🏖️ **Чөлөөний хүсэлт танигдлаа!**\n\n{follow_up}\n\n---\n"
                                    )
                                    leave_request_processed = True
                                else:
                                    # Бүрэн мэдээлэл байвал лидэрт илгээх
                                    teams_service = TeamsAuthService()
                                    
                                    # Teams service готов эсэхийг шалгах
                                    if not hasattr(teams_service, 'webhook_url') or not teams_service.webhook_url:
                                        logger.warning("Teams service тохируулаагүй байна")
                                        await context.send_activity("⚠️ Teams service тохируулаагүй байна.\n\n---\n")
                                        success = False
                                    else:
                                        # Хэрэглэгчийн дэлгэрэнгүй мэдээлэл авах
                                        try:
                                            org_service = OrganizationService()
                                            user_profile = org_service.get_user_profile(user_email) if org_service.headers else None
                                            manager_info = org_service.get_user_manager(user_email) if org_service.headers else None
                                            
                                            if user_profile:
                                                logger.info(f"User profile found: {user_profile.get('displayName')}")
                                            if manager_info:
                                                logger.info(f"Manager found: {manager_info.get('displayName')}")
                                        except Exception as e:
                                            logger.error(f"Error getting user/manager info: {str(e)}")
                                            user_profile = None
                                            manager_info = None
                                        
                                        # Хэрэглэгчийн planner tasks авах (лидэрт илгээхийн тулд)
                                        user_tasks_for_manager = ""
                                        try:
                                            planner = PlannerService()
                                            if hasattr(planner, 'headers') and planner.headers:
                                                planner_tasks = planner.get_user_incomplete_tasks(user_email) or []
                                                personal_tasks = planner.get_personal_tasks(user_email) or []
                                                
                                                if planner_tasks or personal_tasks:
                                                    user_tasks_for_manager = planner.format_tasks_for_display(planner_tasks, personal_tasks)
                                                    logger.info(f"Retrieved tasks for manager: {len(planner_tasks)} planner + {len(personal_tasks)} personal tasks")
                                                else:
                                                    user_tasks_for_manager = "✅ Дутуу даалгавар алга байна"
                                            else:
                                                user_tasks_for_manager = "⚠️ Planner service тохируулаагүй байна"
                                        except Exception as e:
                                            logger.error(f"Error getting user tasks for manager: {str(e)}")
                                            user_tasks_for_manager = "❌ Даалгавар авахад алдаа гарлаа"
                                        
                                        # Лидэрт direct message илгээх (tasks-тай хамт)
                                        manager_email = manager_info.get('mail') if manager_info else None
                                        success = teams_service.send_leave_request_to_manager(leave_analysis, manager_email, user_tasks_for_manager)
                                    
                                    if success:
                                        await context.send_activity(
                                            f"🏖️ **Чөлөөний хүсэлт илгээгдлээ!**\n\n"
                                            f"📋 **Мэдээлэл:**\n"
                                            f"📅 Эхлэх өдөр: {leave_analysis.get('start_date', 'Тодорхойгүй')}\n"
                                            f"📅 Дуусах өдөр: {leave_analysis.get('end_date', 'Тодорхойгүй')}\n"
                                            f"⏰ Нийт цаг: {leave_analysis.get('in_active_hours', 8.0)} цаг\n"
                                            f"📝 Шалтгаан: {leave_analysis.get('reason', 'Дурдаагүй')}\n\n"
                                            f"✅ Таны хүсэлт лидэрт илгээгдлээ. Хариулт хүлээж байна уу.\n\n---\n"
                                        )
                                        leave_request_processed = True
                                    else:
                                        await context.send_activity("⚠️ Чөлөөний хүсэлт илгээхэд алдаа гарлаа.\n\n---\n")
                            else:
                                logger.info("No leave request detected in message")
                                
                        except Exception as e:
                            logger.error(f"Error analyzing leave request: {str(e)}")
                    
                    # AI хариулт (хэрэв чөлөөний хүсэлт эсвэл approval команд биш бол)
                    if not leave_request_processed and not approval_processed:
                        # OpenAI API key шалгах
                        if not openai.api_key:
                            logger.warning("OpenAI API key not configured")
                            await context.send_activity("OpenAI API key тохируулаагүй байна.")
                            return
                        
                        try:
                            # OpenAI API дуудах (шинэ format)
                            client = openai.OpenAI(api_key=openai.api_key)
                            
                            # Хэрэв чөлөөний хүсэлт танигдсан ч нэмэлт асуулт байвал тэмдэглэх
                            system_message = """Та хэрэглэгчийн асистент бот байна. Монгол хэлээр хариулна уу. 
                            Хэрэглэгч транслит (латин үсгээр монгол хэл) эсвэл монгол хэлээр бичиж болно.
                            Транслит жишээ: 'chuluu'=чөлөө, 'margaash'=маргааш, 'tsag'=цаг
                            Хэрэглэгчийн асуултад тохиромжтой, хүүхэд найрсаг хариулт өгнө үү."""
                            
                            response = client.chat.completions.create(
                                model="gpt-4",
                                messages=[
                                    {"role": "system", "content": system_message},
                                    {"role": "user", "content": user_text}
                                ],
                                temperature=0.8
                            )
                            
                            ai_response = response.choices[0].message.content
                            logger.info(f"OpenAI response: {ai_response[:100]}...")
                            await context.send_activity(f"{ai_response}")
                            
                        except Exception as e:
                            logger.error(f"OpenAI API error: {str(e)}")
                            await context.send_activity(f"OpenAI API алдаа: {str(e)}")
                    else:
                        if leave_request_processed:
                            logger.info("Leave request processed, skipping AI response")
                        elif approval_processed:
                            logger.info("Approval command processed, skipping AI response")
                        
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