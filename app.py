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
                    
                    # OpenAI API key шалгах
                    if not openai.api_key:
                        logger.warning("OpenAI API key not configured")
                        await context.send_activity("OpenAI API key тохируулаагүй байна.")
                        return
                    
                    try:
                        # OpenAI API дуудах (шинэ format)
                        client = openai.OpenAI(api_key=openai.api_key)
                        response = client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=[{"role": "user", "content": user_text}]
                        )
                        
                        ai_response = response.choices[0].message.content
                        logger.info(f"OpenAI response: {ai_response[:100]}...")
                        await context.send_activity(f"🤖 **AI хариулт:**\n{ai_response}")
                        
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