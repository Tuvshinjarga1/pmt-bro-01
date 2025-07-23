import os
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import openai
from dotenv import load_dotenv
import asyncio

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

SETTINGS = BotFrameworkAdapterSettings(os.getenv("MICROSOFT_APP_ID"), os.getenv("MICROSOFT_APP_PASSWORD"))
ADAPTER = BotFrameworkAdapter(SETTINGS)

app = Flask(__name__)

# Энгийн health check endpoint
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server is running",
        "endpoints": ["/api/messages"]
    })

@app.route("/api/messages", methods=["POST"])
def process_messages():
    try:
        body = request.get_json()
        
        # Хэрэв body хоосон бол
        if not body:
            return jsonify({"error": "Request body is required"}), 400
            
        activity = Activity().deserialize(body)

        async def logic(context: TurnContext):
            if activity.type == "message":
                user_text = activity.text or "No text provided"
                
                # OpenAI API key байгаа эсэхийг шалгах
                if not openai.api_key:
                    await context.send_activity("OpenAI API key тохируулаагүй байна.")
                    return
                
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": user_text}]
                    )
                    await context.send_activity(response.choices[0].message["content"])
                except Exception as e:
                    await context.send_activity(f"OpenAI API алдаа: {str(e)}")

        # Run async logic in a new event loop
        asyncio.run(ADAPTER.process_activity(activity, "", logic))
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
