import os
import json
import asyncio
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity

MICROSOFT_APP_ID = os.getenv("MICROSOFT_APP_ID")
MICROSOFT_APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD")

SETTINGS = BotFrameworkAdapterSettings(MICROSOFT_APP_ID, MICROSOFT_APP_PASSWORD)
ADAPTER = BotFrameworkAdapter(SETTINGS)

app = Flask(__name__)

CONV_REF_FILE = "conv_ref.json"

@app.route("/api/messages", methods=["POST"])
def messages():
    body = request.get_json()
    activity = Activity().deserialize(body)
    conversation_reference = TurnContext.get_conversation_reference(activity)
    # dict болгож хадгална!
    with open(CONV_REF_FILE, "w", encoding="utf-8") as f:
        json.dump(conversation_reference.dict(), f, ensure_ascii=False)
    return jsonify({"status": "ok"})

async def send_proactive_message(conversation_reference, message_text):
    async def aux_func(turn_context: TurnContext):
        await turn_context.send_activity(message_text)
    await ADAPTER.continue_conversation(conversation_reference, aux_func, MICROSOFT_APP_ID)

@app.route("/send_proactive", methods=["POST"])
def send_proactive():
    try:
        with open(CONV_REF_FILE, "r", encoding="utf-8") as f:
            conversation_reference = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Conversation reference олдсонгүй: {str(e)}"}), 400

    data = request.get_json()
    message_text = data.get("message", "hi, snu")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_proactive_message(conversation_reference, message_text))
    return jsonify({"result": "Proactive мессеж илгээгдлээ!"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
