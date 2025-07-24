# Teams Bot Application - Unified Architecture

Энэ Teams bot application нь **нэг entry point** (`main.py`) ашиглан бүх сервисүүдийг нэгтгэсэн архитектуртай.

## 🏗️ Architecture

### Single Entry Point

- `main.py` - **Гол entry point** - Teams AI bot + health endpoints + бүх сервисүүд

### Core Components

- `bot.py` - Teams AI logic, чөлөөний хүсэлт, manager approval
- `config.py` - Environment variables-аас configuration авах
- `planner_service.py` - Microsoft Graph API Planner tasks
- `auth_service.py` - OAuth authentication service
- `app.py` - Хуучин Flask bot (одоо ашиглахгүй)

### Support Files

- `startup.sh` - Azure App Service startup script
- `test_integration.py` - Бүх компонент ажиллаж байгаа эсэх тест
- `requirements.txt` - Python dependencies
- `.gitignore` - Нууц файлуудыг Git-д оруулахгүй байх

---

## 🔧 Environment Variables

`.env` файл үүсгээд дараах environment variables тохируулна:

```bash
# Bot Framework Configuration
BOT_ID=your-bot-app-id
BOT_PASSWORD=your-bot-password
BOT_TYPE=MultiTenant
BOT_TENANT_ID=your-tenant-id

# OpenAI Configuration
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL_NAME=gpt-4

# Microsoft Graph API
GRAPH_TENANT_ID=your-tenant-id
GRAPH_CLIENT_ID=your-client-id
GRAPH_CLIENT_SECRET=your-client-secret

# Server URLs (optional, defaults provided)
AI_SERVER_URL=https://ai-server-production-0014.up.railway.app
MCP_SERVER_URL=https://mcp-server-production-6219.up.railway.app
TEAMS_WEBHOOK_URL=your-teams-webhook-url

# Port (optional, defaults to 8000)
PORT=8000
```

---

## 🚀 How to Run

### Local Development

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env file with your configuration
cp .env.example .env
# Edit .env with your actual values

# 3. Test integration
python test_integration.py

# 4. Start the application
python main.py
```

### Azure Deployment

1. **Environment variables тохируулах** Azure Portal дээр
2. **Startup command**: `./startup.sh`
3. **Push код** GitHub руу - GitHub Actions автоматаар deploy хийнэ

---

## 🎯 Features

### 🤖 Bot Capabilities

- **AI-powered чөлөөний хүсэлт** - Хэрэглэгч ярианаар чөлөө хүснэ
- **Автомат мэдээлэл авах** - Planner + To-Do tasks шалгана
- **Manager approval workflow** - Чөлөөний хүсэлтийг manager-т илгээх
- **Teams webhook мэдэгдэл** - Approve/reject үед автомат мэдэгдэх
- **MCP server integration** - Чөлөөний хүсэлтийг системд хадгална

### 🌐 Health Endpoints

- `GET /` - Энгийн health check
- `GET /health` - Дэлгэрэнгүй service status
- `POST /api/messages` - Teams bot messages (Teams AI автоматаар)

---

## 🧪 Testing

```bash
# Integration test ажиллуулах
python test_integration.py
```

Энэ тест дараах зүйлсийг шалгана:

- ✅ Бүх imports амжилттай эсэх
- ✅ Configuration зөв тохируулагдсан эсэх
- ✅ Services initialize болох эсэх
- ✅ Teams AI bot ажиллаж байгаа эсэх
- ✅ Health endpoints бүртгэгдсэн эсэх

---

## 📁 File Structure

```
pmt-bot-api/
├── main.py              # 🎯 UNIFIED ENTRY POINT
├── bot.py               # Teams AI bot logic
├── config.py            # Configuration management
├── planner_service.py   # Microsoft Graph API service
├── auth_service.py      # OAuth authentication
├── requirements.txt     # Python dependencies
├── startup.sh          # Azure startup script
├── test_integration.py # Integration tests
├── .gitignore          # Git ignore rules
├── .env                # Environment variables (не для git)
└── README.md           # This documentation
```

---

## 🔍 Troubleshooting

### Common Issues

1. **ModuleNotFoundError: No module named 'teams'**

   ```bash
   pip install teams-ai
   ```

2. **Environment variables not found**

   - `.env` файл үүсгэсэн эсэхээ шалга
   - Azure дээр environment variables тохируулсан эсэхээ шалга

3. **Health check fails**

   ```bash
   curl http://localhost:8000/health
   ```

4. **Integration test fails**
   ```bash
   python test_integration.py
   # Алдааны дэлгэрэнгүй мэдээллийг харна
   ```

### Debug Commands

```bash
# Test imports
python -c "import main, bot, config; print('✅ All modules OK')"

# Test configuration
python -c "from config import Config; c=Config(); print(f'Port: {c.PORT}')"

# Test services
python -c "from planner_service import PlannerService; print('✅ Planner OK')"

# Full integration test
python test_integration.py
```

---

## 🎉 Benefits of Unified Architecture

✅ **Single Entry Point** - Бүх зүйл `main.py`-аас эхэлнэ  
✅ **All Services Integrated** - config, planner, auth, bot бүгд холбогдсон  
✅ **Health Monitoring** - Azure App Service health checks  
✅ **Easy Deployment** - Нэг команд: `python main.py`  
✅ **Environment Flexibility** - .env файл + Azure environment variables  
✅ **Comprehensive Testing** - Бүх компонентыг нэгэн зэрэг тест хийнэ

---

## 🚀 Ready to Deploy!

1. **Environment variables тохируул**
2. **Test integration: `python test_integration.py`**
3. **Start application: `python main.py`**
4. **Push to GitHub for automatic Azure deployment**

Unified architecture бэлэн! 🎯
