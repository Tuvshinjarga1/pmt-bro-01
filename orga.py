import asyncio
from msgraph import GraphServiceClient
from azure.identity.aio import ClientSecretCredential
import requests

TENANT_ID = ""
CLIENT_ID = ""
CLIENT_SECRET = ""

async def main():
    # 1. Auth credential үүсгэнэ
    credential = ClientSecretCredential(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )

    try:
        # 2. GraphServiceClient үүсгэнэ
        graph_client = GraphServiceClient(credentials=credential, scopes=["https://graph.microsoft.com/.default"])

        # 3. Менежерийн мэдээлэл авах
        user_email = "tuvshinjargal@fibo.cloud"  # Энд email-ээ оруулна
        result = await graph_client.users.by_user_id(user_email).manager.get()
        
        if result:
            manager_upn = result.user_principal_name
            print(f"Менежер: {manager_upn}")
            
            # 4. Токен авах (шинэ credential үүсгэх)
            token_credential = ClientSecretCredential(
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )
            
            try:
                access_token = await token_credential.get_token("https://graph.microsoft.com/.default")
                headers = {
                    "Authorization": f"Bearer {access_token.token}",
                    "Content-Type": "application/json"
                }

                # 5. Чат үүсгэх
                chat_url = "https://graph.microsoft.com/v1.0/chats"
                chat_data = {
                    "chatType": "oneOnOne",
                    "members": [
                        {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "roles": ["owner"],
                            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{manager_upn}')"
                        },
                        {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "roles": ["owner"],
                            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user_email}')"
                        }
                    ]
                }
                
                print("Чат үүсгэж байна...")
                chat_response = requests.post(chat_url, headers=headers, json=chat_data)
                
                if chat_response.status_code == 201:
                    chat_id = chat_response.json()["id"]
                    print(f"Чат үүсгэгдлээ: {chat_id}")
                    
                    # 6. Adaptive Card илгээх
                    adaptive_card_content = {
                        "type": "AdaptiveCard",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": f"{user_email} хэрэглэгчийн leave хүсэлтийг зөвшөөрөх үү?",
                                "wrap": True
                            }
                        ],
                        "actions": [
                            {
                                "type": "Action.Submit",
                                "title": "Зөвшөөрөх",
                                "data": {"action": "approve"}
                            },
                            {
                                "type": "Action.Submit",
                                "title": "Татгалзах",
                                "data": {"action": "reject"}
                            }
                        ],
                        "version": "1.4"
                    }

                    message_url = f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages"
                    message_data = {
                        "body": {
                            "contentType": "html",
                            "content": "Leave хүсэлтийн шийдвэр"
                        },
                        "attachments": [
                            {
                                "contentType": "application/vnd.microsoft.card.adaptive",
                                "content": adaptive_card_content
                            }
                        ]
                    }
                    
                    print("Мессеж илгээж байна...")
                    message_response = requests.post(message_url, headers=headers, json=message_data)
                    
                    if message_response.status_code == 201:
                        print("Мессеж амжилттай илгээгдлээ!")
                    else:
                        print(f"Мессеж илгээхэд алдаа: {message_response.status_code}")
                        print(message_response.text)
                else:
                    print(f"Чат үүсгэхэд алдаа: {chat_response.status_code}")
                    print(chat_response.text)
                    
            finally:
                await token_credential.close()
        else:
            print("Менежер олдсонгүй")
            
    finally:
        await credential.close()

if __name__ == "__main__":
    asyncio.run(main())
