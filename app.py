import os
import logging
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import asyncio
import json
from botbuilder.schema import ConversationReference

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

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server is running",
        "endpoints": ["/api/messages"],
        "app_id_configured": bool(os.getenv("MICROSOFT_APP_ID"))
    })

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

        # Conversation reference хадгалах
        reference = TurnContext.get_conversation_reference(activity)
        with open("conversation_reference.json", "w", encoding="utf-8") as f:
            json.dump(reference.serialize(), f, ensure_ascii=False, indent=2)

        async def logic(context: TurnContext):
            try:
                if activity.type == "message":
                    user_text = activity.text or "No text provided"
                    logger.info(f"Processing message: {user_text}")
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

@app.route("/proactive-message", methods=["POST"])
def proactive_message():
    data = request.json
    message_text = data.get("message", "Сайн байна уу!")
    try:
        # Хадгалсан conversation reference-г унших
        with open("conversation_reference.json", "r", encoding="utf-8") as f:
            ref_data = json.load(f)
        conversation_reference = ConversationReference().deserialize(ref_data)

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
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Proactive message error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)