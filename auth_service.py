"""
OAuth authentication service for Microsoft Graph API
"""

import os
import json
import aiohttp
from typing import Optional, Dict
from botbuilder.core import TurnContext, MessageFactory
from botbuilder.schema import TokenResponse, OAuthCard, CardAction, ActionTypes


class AuthService:
    """Service to handle OAuth authentication for Microsoft Graph"""
    
    def __init__(self):
        self.connection_name = "GraphConnection"  # OAuth connection name
        self.scopes = [
            "https://graph.microsoft.com/User.Read",
            "https://graph.microsoft.com/Group.Read.All", 
            "https://graph.microsoft.com/Tasks.ReadWrite"
        ]
    
    async def get_access_token(self, context: TurnContext) -> Optional[str]:
        """
        Get access token for Microsoft Graph API
        
        Args:
            context: Turn context
            
        Returns:
            Access token or None if not authenticated
        """
        try:
            # Try to get token from the user token service
            if hasattr(context.adapter, 'get_user_token'):
                token_response = await context.adapter.get_user_token(
                    context,
                    self.connection_name
                )
                
                if token_response and token_response.token:
                    return token_response.token
            
            # Try to get token from turn state
            if "access_token" in context.turn_state:
                return str(context.turn_state["access_token"])
                    
        except Exception as e:
            print(f"Error getting access token: {e}")
            
        return None
    
    async def sign_in_user(self, context: TurnContext) -> None:
        """
        Initiate sign-in flow for the user
        
        Args:
            context: Turn context
        """
        try:
            # Send sign-in message (OAuth card would require proper bot framework setup)
            await context.send_activity(
                "🔐 Microsoft Graph эрхийг баталгаажуулах шаардлагатай байна. "
                "Bot Framework OAuth тохиргоо шаардлагатай."
            )
            
        except Exception as e:
            print(f"Error initiating sign-in: {e}")
            await context.send_activity(
                "⚠️ Нэвтрэх процессийг эхлүүлэхэд алдаа гарлаа."
            )
    
    async def handle_token_response(self, context: TurnContext) -> bool:
        """
        Handle token response from OAuth flow
        
        Args:
            context: Turn context
            
        Returns:
            True if token was successfully handled
        """
        try:
            if context.activity.type == "event" and context.activity.name == "tokens/response":
                # Extract token from the response
                token_response = context.activity.value
                if token_response and token_response.get("token"):
                    # Store token for later use
                    context.turn_state["access_token"] = token_response["token"]
                    return True
                    
        except Exception as e:
            print(f"Error handling token response: {e}")
            
        return False
    
    def create_oauth_prompt(self) -> Dict:
        """
        Create OAuth prompt for authentication
        
        Returns:
            OAuth prompt configuration
        """
        return {
            "type": "OAuth",
            "settings": {
                "connectionName": self.connection_name,
                "title": "Microsoft Graph-д нэвтрэх",
                "text": "Таны planner болон to-do даалгавруудыг харахын тулд Microsoft Graph API-д нэвтрэх шаардлагатай.",
                "timeout": 300000,  # 5 minutes
                "endOnInvalidMessage": True
            }
        }
    
    async def validate_token(self, access_token: str) -> bool:
        """
        Validate the access token by making a simple Graph API call
        
        Args:
            access_token: The access token to validate
            
        Returns:
            True if token is valid
        """
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://graph.microsoft.com/v1.0/me",
                    headers=headers
                ) as response:
                    return response.status == 200
                    
        except Exception as e:
            print(f"Error validating token: {e}")
            return False 