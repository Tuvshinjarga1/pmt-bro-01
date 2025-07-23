import os
from aiohttp import web
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import openai
from dotenv import load_dotenv

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

# Bot Framework
SETTINGS = BotFrameworkAdapterSettings(os.getenv("MICROSOFT_APP_ID"), os.getenv("MICROSOFT_APP_PASSWORD"))
ADAPTER = BotFrameworkAdapter(SETTINGS)

async def process_activity(req):
    body = await req.json()
    activity = Activity().deserialize(body)

    async def logic(context: TurnContext):
        if activity.type == "message":
            user_text = activity.text
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": user_text}]
            )
            await context.send_activity(response.choices[0].message["content"])

    await ADAPTER.process_activity(activity, "", logic)
    return web.Response(status=200)

app = web.Application()
app.router.add_post("/api/messages", process_activity)

if __name__ == "__main__":
    web.run_app(app, port=3978)
