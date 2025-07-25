import asyncio
from msgraph import GraphServiceClient
from azure.identity.aio import ClientSecretCredential

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

    # 2. GraphServiceClient үүсгэнэ
    # credentials гэж бичнэ!
    graph_client = GraphServiceClient(credentials=credential, scopes=["https://graph.microsoft.com/.default"])

    # 3. Менежерийн мэдээлэл авах
    user_email = "tuvshinjargal@fibo.cloud"  # Энд email-ээ оруулна
    result = await graph_client.users.by_user_id(user_email).manager.get()
    # print(result)
    print(result.user_principal_name)

    await credential.close()

if __name__ == "__main__":
    asyncio.run(main())
