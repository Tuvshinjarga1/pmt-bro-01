import os
import logging
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import openai
from dotenv import load_dotenv
import asyncio

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

# Error handlerr
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)