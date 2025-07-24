"""
Unified entry point for Teams Bot Application
Combines Teams AI bot with health check endpoints and all services
"""

import os
import logging
from flask import jsonify
from bot import bot_app, config

# Logging тохиргоо
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Health check endpoint нэмэх Teams AI app дээр
@bot_app.app.route("/", methods=["GET"])
def health_check():
    """Health check endpoint for Azure App Service"""
    return jsonify({
        "status": "running",
        "message": "Teams Bot Server is running",
        "endpoints": ["/api/messages"],
        "app_id_configured": bool(config.APP_ID),
        "openai_configured": bool(config.OPENAI_API_KEY),
        "graph_configured": bool(config.GRAPH_CLIENT_ID),
        "teams_ai": True,
        "services": {
            "planner_service": True,
            "auth_service": True,
            "config": True
        }
    })

# Additional health endpoint for detailed status
@bot_app.app.route("/health", methods=["GET"])
def detailed_health():
    """Detailed health check with service status"""
    try:
        # Test planner service
        from planner_service import PlannerService
        planner = PlannerService()
        planner_status = True
    except Exception as e:
        logger.error(f"Planner service error: {e}")
        planner_status = False
    
    try:
        # Test auth service
        from auth_service import AuthService
        auth = AuthService()
        auth_status = True
    except Exception as e:
        logger.error(f"Auth service error: {e}")
        auth_status = False
    
    return jsonify({
        "status": "detailed_health",
        "services": {
            "teams_ai_bot": True,
            "planner_service": planner_status,
            "auth_service": auth_status,
            "config": bool(config.OPENAI_API_KEY),
            "graph_api": bool(config.GRAPH_CLIENT_ID and config.GRAPH_CLIENT_SECRET)
        },
        "configuration": {
            "port": config.PORT,
            "openai_model": config.OPENAI_MODEL_NAME,
            "ai_server_url": config.AI_SERVER_URL,
            "mcp_server_url": config.MCP_SERVER_URL
        }
    })

# Error handler
@bot_app.app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

# Entry point
if __name__ == "__main__":
    logger.info("🚀 Starting unified Teams Bot application...")
    logger.info(f"📊 Configuration:")
    logger.info(f"   - Port: {config.PORT}")
    logger.info(f"   - Bot App ID: {config.APP_ID[:10]}..." if config.APP_ID else "   - Bot App ID: Not configured")
    logger.info(f"   - OpenAI API: {'✅ Configured' if config.OPENAI_API_KEY else '❌ Not configured'}")
    logger.info(f"   - Graph API: {'✅ Configured' if config.GRAPH_CLIENT_ID else '❌ Not configured'}")
    logger.info(f"   - AI Server: {config.AI_SERVER_URL}")
    logger.info(f"   - MCP Server: {config.MCP_SERVER_URL}")
    
    # Test services on startup
    try:
        from planner_service import PlannerService
        planner = PlannerService()
        logger.info("✅ Planner service initialized")
    except Exception as e:
        logger.error(f"❌ Planner service failed: {e}")
    
    try:
        from auth_service import AuthService
        auth = AuthService()
        logger.info("✅ Auth service initialized")
    except Exception as e:
        logger.error(f"❌ Auth service failed: {e}")
    
    logger.info("🎯 Starting Teams AI bot server...")
    
    # Start the Teams AI application
    bot_app.start(config.PORT) 