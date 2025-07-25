from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ConversationReference
import os, asyncio

MICROSOFT_APP_ID = 'fbca8d51-1a7f-46f0-a634-8cf2d8344bb4'
MICROSOFT_APP_PASSWORD = ''

SETTINGS = BotFrameworkAdapterSettings(MICROSOFT_APP_ID, MICROSOFT_APP_PASSWORD)
ADAPTER = BotFrameworkAdapter(SETTINGS)

# Энэ conversation_reference-г хэрэглэгч танай бот руу анх бичихэд хадгалж авсан байх ёстой!
conversation_reference = {
    "channelId": "msteams",
    "serviceUrl": "https://smba.trafficmanager.net/emea/",  # тухайн хэрэглэгчийн serviceUrl
    "conversation": {"id": "<conversation_id>"},
    "bot": {"id": MICROSOFT_APP_ID},
    "user": {"id": "<user_aad_id>"}
}

async def send_proactive_message(conversation_reference, message_text):
    async def aux_func(turn_context: TurnContext):
        await turn_context.send_activity(message_text)
    await ADAPTER.continue_conversation(ConversationReference(**conversation_reference), aux_func, MICROSOFT_APP_ID)

# Flask endpoint-оос дуудах жишээ
@app.route("/send_hi_snu", methods=["POST"])
def send_hi_snu():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(send_proactive_message(conversation_reference, "hi, snu"))
    return {"result": "Мессеж илгээгдсэн!"}