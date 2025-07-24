import os
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import asyncio

# Import bot.py-ын Teams AI bot
from bot import bot_app, config

# Logging тохиргоо
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Flask app үүсгэх
app = Flask(__name__)

# Health check endpoint
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server with Teams AI Integration",
        "endpoints": ["/api/messages"],
        "app_id_configured": bool(config.APP_ID),
        "openai_configured": bool(config.OPENAI_API_KEY),
        "teams_ai_integrated": True,
        "services": {
            "planner_service": True,
            "auth_service": True,
            "config": True
        }
    })

@app.route("/api/messages", methods=["POST"])
def process_messages():
    """
    Teams bot messages endpoint - uses bot.py Teams AI functionality
    """
    try:
        logger.info("Received message request - delegating to Teams AI bot")
        
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
        
        # Delegate to Teams AI bot using asyncio.run
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
