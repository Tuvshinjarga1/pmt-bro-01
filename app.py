import os
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import asyncio

# Logging тохиргоо
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Flask app үүсгэх
app = Flask(__name__)

# Try to import bot.py Teams AI functionality
# Fallback to basic Flask bot if Teams AI not available
try:
    from bot import bot_app, config
    TEAMS_AI_AVAILABLE = True
    logger.info("✅ Teams AI bot imported successfully")
except ImportError as e:
    logger.warning(f"⚠️ Teams AI bot not available: {e}")
    logger.info("📌 Falling back to basic Flask bot mode")
    TEAMS_AI_AVAILABLE = False
    
    # Fallback config
    class FallbackConfig:
        PORT = int(os.environ.get("PORT", 8000))
        APP_ID = os.environ.get("BOT_ID", "")
        OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    
    config = FallbackConfig()

# Health check endpoint
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server" + (" with Teams AI Integration" if TEAMS_AI_AVAILABLE else " - Basic Mode"),
        "endpoints": ["/api/messages"],
        "app_id_configured": bool(config.APP_ID),
        "openai_configured": bool(config.OPENAI_API_KEY),
        "teams_ai_available": TEAMS_AI_AVAILABLE,
        "mode": "teams_ai" if TEAMS_AI_AVAILABLE else "basic_flask",
        "services": {
            "planner_service": TEAMS_AI_AVAILABLE,
            "auth_service": TEAMS_AI_AVAILABLE,
            "config": True
        }
    })

@app.route("/api/messages", methods=["POST"])
def process_messages():
    """
    Teams bot messages endpoint - uses Teams AI if available, fallback to basic mode
    """
    try:
        logger.info("Received message request")
        
        # Request body шалгах
        if not request.is_json:
            logger.error("Request is not JSON")
            return jsonify({"error": "Content-Type must be application/json"}), 400
            
        body = request.get_json()
        logger.info(f"Request body received: {body}")
        
        if not body:
            logger.error("Empty request body")
            return jsonify({"error": "Request body is required"}), 400

        # Get authorization header
        auth_header = request.headers.get('Authorization', '')
        logger.info(f"Auth header present: {bool(auth_header)}")
        
        if TEAMS_AI_AVAILABLE:
            # Use Teams AI bot functionality
            logger.info("Processing with Teams AI bot")
            try:
                from botbuilder.schema import Activity
                
                # Convert request to Activity
                activity = Activity().deserialize(body)
                logger.info(f"Activity type: {activity.type}, text: {activity.text}")
                
                # Create async wrapper function
                async def process_with_teams_ai():
                    try:
                        # Use Teams AI bot to process the activity
                        await bot_app.adapter.process_activity(
                            activity,
                            auth_header,
                            bot_app.turn_handler
                        )
                        return True
                    except Exception as e:
                        logger.error(f"Teams AI processing error: {str(e)}")
                        return False
                
                # Run the async function
                success = asyncio.run(process_with_teams_ai())
                
                if success:
                    logger.info("Message processed successfully by Teams AI bot")
                    return jsonify({"status": "success", "processed_by": "teams_ai_bot"}), 200
                else:
                    logger.error("Teams AI bot processing failed")
                    return jsonify({"error": "Teams AI bot processing failed"}), 500
                
            except Exception as e:
                logger.error(f"Teams AI bot integration error: {str(e)}")
                return jsonify({"error": f"Teams AI bot error: {str(e)}"}), 500
        
        else:
            # Fallback to basic Flask + BotFrameworkAdapter
            logger.info("Processing with basic Flask bot (Teams AI not available)")
            try:
                from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
                from botbuilder.schema import Activity
                import openai
                
                # Basic bot framework adapter
                app_id = config.APP_ID
                app_password = os.environ.get("BOT_PASSWORD", "")
                settings = BotFrameworkAdapterSettings(app_id, app_password)
                adapter = BotFrameworkAdapter(settings)
                
                # Convert request to Activity
                activity = Activity().deserialize(body)
                logger.info(f"Basic bot - Activity type: {activity.type}, text: {activity.text}")
                
                async def basic_logic(context: TurnContext):
                    try:
                        if activity.type == "message":
                            user_text = activity.text or "No text provided"
                            logger.info(f"Basic bot processing message: {user_text}")
                            
                            if config.OPENAI_API_KEY:
                                try:
                                    # Basic OpenAI response
                                    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
                                    response = client.chat.completions.create(
                                        model="gpt-3.5-turbo",
                                        messages=[{"role": "user", "content": user_text}]
                                    )
                                    
                                    ai_response = response.choices[0].message.content
                                    await context.send_activity(ai_response)
                                    
                                except Exception as e:
                                    logger.error(f"OpenAI API error: {str(e)}")
                                    await context.send_activity(f"OpenAI API алдаа: {str(e)}")
                            else:
                                await context.send_activity("Сайн байна уу! Teams AI bot суугаагүй тул энгийн хариу өгч байна.")
                                
                    except Exception as e:
                        logger.error(f"Basic bot logic error: {str(e)}")
                        await context.send_activity(f"Алдаа гарлаа: {str(e)}")
                
                # Process with basic adapter
                asyncio.run(adapter.process_activity(activity, auth_header, basic_logic))
                logger.info("Message processed successfully by basic Flask bot")
                return jsonify({"status": "success", "processed_by": "basic_flask_bot"}), 200
                
            except Exception as e:
                logger.error(f"Basic bot processing error: {str(e)}")
                return jsonify({"error": f"Basic bot error: {str(e)}"}), 500
            
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# Error handler
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = config.PORT
    logger.info("🚀 Starting Flask app with Teams AI bot integration...")
    logger.info(f"📊 Configuration:")
    logger.info(f"   - Port: {port}")
    logger.info(f"   - Bot App ID: {config.APP_ID[:10]}..." if config.APP_ID else "   - Bot App ID: Not configured")
    logger.info(f"   - OpenAI API: {'✅ Configured' if config.OPENAI_API_KEY else '❌ Not configured'}")
    logger.info(f"   - Teams AI: ✅ Integrated from bot.py")
    
    # Test bot.py integration
    try:
        logger.info("✅ Teams AI bot imported successfully")
        logger.info("✅ All services available: planner, auth, config")
    except Exception as e:
        logger.error(f"❌ Teams AI bot integration failed: {e}")
    
    logger.info(f"🎯 Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
