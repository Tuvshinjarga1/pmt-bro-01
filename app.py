"""
Complete Teams Bot Implementation for Leave Request Approval
with Proactive Messaging to Managers
"""

import asyncio
import json
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext, MessageFactory
from botbuilder.schema import ConversationReference
import os
import logging
from datetime import datetime

app = Flask(__name__)

# Flask log тохиргоо
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

@app.before_request
def log_request_info():
    logging.info(f"REQUEST: {request.method} {request.path}")
    if request.data:
        try:
            logging.info(f"Request body: {request.data.decode('utf-8')}")
        except Exception:
            pass

# Ботын тохиргоо
BOT_APP_ID = os.getenv("MICROSOFT_APP_ID")
BOT_APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD")
TEAMS_SERVICE_URL = "https://smba.trafficmanager.net/teams/"
TEAMS_CHANNEL_ID = "msteams"

settings = BotFrameworkAdapterSettings(app_id=BOT_APP_ID, app_password=BOT_APP_PASSWORD)
adapter = BotFrameworkAdapter(settings)

# 1. Teams-ээс мессеж ирэхэд conversation reference хадгалах endpoint
@app.route("/api/messages", methods=["POST"])
def messages():
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
    else:
        return jsonify({"error": "Invalid content type"}), 400

    activity = TurnContext.deserialize_activity(body)
    reference = TurnContext.get_conversation_reference(activity)
    # Лог болон файлд хадгална
    logging.info("==== CONVERSATION REFERENCE ====")
    logging.info(json.dumps(reference.serialize(), indent=2, ensure_ascii=False))
    with open("conversation_reference.json", "w", encoding="utf-8") as f:
        json.dump(reference.serialize(), f, ensure_ascii=False, indent=2)

    # Activity дэлгэрэнгүй log
    logging.info(f"Activity type: {getattr(activity, 'type', None)}")
    logging.info(f"From: {getattr(activity.from_property, 'id', None)} | Text: {getattr(activity, 'text', None)}")

    # ECHO: хэрэглэгчийн мессежийг буцааж илгээх
    async def echo_callback(context: TurnContext):
        await context.send_activity(MessageFactory.text(activity.text))
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(
        adapter.process_activity(activity, "", echo_callback)
    )
    return "", 200

# 2. Proactive мессеж илгээх endpoint
async def send_proactive_message(message_text: str):
    # Хадгалсан conversation reference-ийг уншина
    with open("conversation_reference.json", "r", encoding="utf-8") as f:
        ref_data = json.load(f)
    conversation_reference = ConversationReference().deserialize(ref_data)
    async def send_message_callback(context: TurnContext):
        await context.send_activity(MessageFactory.text(message_text))
    await adapter.continue_conversation(
        conversation_reference,
        send_message_callback,
        BOT_APP_ID
    )

@app.route("/proactive-message", methods=["POST"])
def proactive_message():
    data = request.json
    message_text = data.get("message", "Сайн байна уу!")
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(send_proactive_message(message_text))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3978)