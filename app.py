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
# Leave request болон Teams messaging services
from leave_request_service import LeaveRequestService
from teams_auth_service import TeamsAuthService

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
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server is running",
        "endpoints": ["/api/messages"],
        "app_id_configured": bool(os.getenv("MICROSOFT_APP_ID")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY"))
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
                    
                    # Эхлээд planner tasks-уудыг шалгах
                    tasks_message = ""
                    if user_email and user_email != "unknown_user":
                        try:
                            logger.info(f"Getting planner tasks for user: {user_email}")
                            planner = PlannerService()
                            
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
                        logger.info("No valid user email found, skipping planner tasks check")
                    
                    # NLP ашиглан чөлөөний хүсэлт шалгах
                    leave_request_processed = False
                    if user_email and user_email != "unknown_user":
                        try:
                            logger.info(f"Analyzing message for leave request: {user_text[:100]}...")
                            leave_service = LeaveRequestService()
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
                                    success = teams_service.send_leave_request_to_manager(leave_analysis)
                                    
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
                    
                    # AI хариулт (хэрэв чөлөөний хүсэлт биш эсвэл нэмэлт асуулт байвал)
                    if not leave_request_processed:
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
                        logger.info("Leave request processed, skipping AI response")
                        
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