import os
from flask import Flask, request, jsonify
from azure.identity.aio import ClientSecretCredential
import requests
import asyncio

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

app = Flask(__name__)

async def send_snu_message(user_email):
    credential = ClientSecretCredential(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    try:
        access_token = await credential.get_token("https://graph.microsoft.com/.default")
        headers = {
            "Authorization": f"Bearer {access_token.token}",
            "Content-Type": "application/json"
        }
        chat_url = "https://graph.microsoft.com/v1.0/chats"
        chat_data = {
            "chatType": "oneOnOne",
            "members": [
                {
<<<<<<< HEAD
                    "@odata.type": "#microsoft.graph.aadUserConversationMember", 
=======
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
>>>>>>> 0c55af86a0547c214a78ccce87983924274222c0
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user_email}')"
                }
            ]
        }
        chat_response = requests.post(chat_url, headers=headers, json=chat_data)
<<<<<<< HEAD
        
=======
>>>>>>> 0c55af86a0547c214a78ccce87983924274222c0
        if chat_response.status_code in [201, 409]:
            chat_id = chat_response.json().get("id")
            if not chat_id:
                return "Чат ID олдсонгүй"
        else:
<<<<<<< HEAD
            # Дэлгэрэнгүй алдааны мэдээлэл харуулах
            try:
                error_detail = chat_response.json()
                return f"Чат үүсгэхэд алдаа: {chat_response.status_code} - {error_detail}"
            except:
                return f"Чат үүсгэхэд алдаа: {chat_response.status_code} - {chat_response.text}"
        
=======
            return f"Чат үүсгэхэд алдаа: {chat_response.status_code}"
>>>>>>> 0c55af86a0547c214a78ccce87983924274222c0
        message_url = f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages"
        message_data = {
            "body": {
                "contentType": "text",
                "content": "snu"
            }
        }
        message_response = requests.post(message_url, headers=headers, json=message_data)
<<<<<<< HEAD
        
        if message_response.status_code == 201:
            return "Мессеж амжилттай илгээгдлээ!"
        else:
            # Дэлгэрэнгүй алдааны мэдээлэл харуулахх
            try:
                error_detail = message_response.json()
                return f"Мессеж илгээхэд алдаа: {message_response.status_code} - {error_detail}"
            except:
                return f"Мессеж илгээхэд алдаа: {message_response.status_code} - {message_response.text}"
=======
        if message_response.status_code == 201:
            return "Мессеж амжилттай илгээгдлээ!"
        else:
            return f"Мессеж илгээхэд алдаа: {message_response.status_code}"
>>>>>>> 0c55af86a0547c214a78ccce87983924274222c0
    finally:
        await credential.close()

@app.route("/send_snu", methods=["POST"])
def send_snu():
    data = request.get_json()
    user_email = data.get("user_email")
    if not user_email:
        return jsonify({"error": "user_email шаардлагатай"}), 400
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(send_snu_message(user_email))
    return jsonify({"result": result})

if __name__ == "__main__":
<<<<<<< HEAD
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
=======
    app.run(host="0.0.0.0", port=8000, debug=True)
>>>>>>> 0c55af86a0547c214a78ccce87983924274222c0
