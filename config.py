"""
Copyright (c) Microsoft Corporation. All rights reserved.
Licensed under the MIT License.
"""

import os

from dotenv import load_dotenv

load_dotenv()

class Config:
    """Bot Configuration"""

    PORT = 3978
    APP_ID = os.environ.get("BOT_ID", "")
    APP_PASSWORD = os.environ.get("BOT_PASSWORD", "")
    APP_TYPE = os.environ.get("BOT_TYPE", "")
    APP_TENANTID = os.environ.get("BOT_TENANT_ID", "")
    OPENAI_API_KEY = os.environ["OPENAI_API_KEY"] # OpenAI API key
    OPENAI_MODEL_NAME='gpt-4' # OpenAI model name. You can use any other model name from OpenAI.
    
    # Microsoft Graph API credentials
    GRAPH_TENANT_ID = os.environ.get("GRAPH_TENANT_ID", "3fee1c11-7cdf-44b4-a1b0-5183408e1d89")
    GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "a6e958a7-e8df-4e83-a8c2-5dc73f93bdc4") 
    GRAPH_CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET")

    # Deployed server URLs
    AI_SERVER_URL = "https://ai-server-production-0014.up.railway.app"
    MCP_SERVER_URL = "https://mcp-server-production-6219.up.railway.app"
    
    # Teams webhook URL for notifications
    TEAMS_WEBHOOK_URL = "https://fibocloudmn.webhook.office.com/webhookb2/661d5c20-ce88-4fc4-ae3f-843ba7b1fecc@3fee1c11-7cdf-44b4-a1b0-5183408e1d89/IncomingWebhook/d835790d3e7844bc8ef8059060ecdd4d/e66e1c65-f5db-4a87-95e1-9dbebc412afe/V2yaMpY1jDY7oxwlTb2D9BMg9M4wCYqKcLWEyQ6h8Q8p81"
