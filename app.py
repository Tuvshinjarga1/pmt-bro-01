import os
import logging
from flask import Flask, request, jsonify
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext, MessageFactory
from botbuilder.schema import Activity, Attachment
import asyncio
import json
from botbuilder.schema import ConversationReference
import re
from datetime import datetime, timedelta
import uuid
import openai
from openai import OpenAI
import requests
import threading
import time
from typing import Dict, List, Optional
from urllib.parse import quote
import uuid as _uuid_for_validation

# Assign planner import
from assign_planner import TaskAssignmentManager, get_cached_access_token

# Config import
from config import Config

# Microsoft Planner tasks авах
try:
    from get_tasks import get_access_token, MicrosoftPlannerTasksAPI
    PLANNER_AVAILABLE = True
except ImportError:
    PLANNER_AVAILABLE = False
    logging.warning("get_tasks module not found. Planner functionality disabled.")

# Leader.py-аас manager олох функцүүд import хийх
try:
    from leader import get_user_manager_id, get_user_manager_info
    LEADER_AVAILABLE = True
except ImportError:
    LEADER_AVAILABLE = False
    logging.warning("leader module not found. Dynamic manager lookup disabled.")

# Jobtitle.py-аас CEO олох функцүүд import хийх
try:
    from jobtitle import MicrosoftUsersAPI as JobTitleAPI
    JOBTITLE_AVAILABLE = True
except ImportError:
    JOBTITLE_AVAILABLE = False
    logging.warning("jobtitle module not found. CEO lookup disabled.")

# All_user.py-аас бүх хэрэглэгчдийн мэдээлэл авах функцүүд import хийх
try:
    from all_user import get_access_token, MicrosoftUsersAPI as AllUsersAPI
    ALL_USERS_AVAILABLE = True
except ImportError:
    ALL_USERS_AVAILABLE = False
    logging.warning("all_user module not found. All users lookup disabled.")

# Logging тохиргоо
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI тохиргоо
openai_client = OpenAI(
    api_key=Config.OPENAI_API_KEY if hasattr(Config, 'OPENAI_API_KEY') else os.getenv("OPENAI_API_KEY", "")
)

# Bot Framework тохиргоо
app_id = os.getenv("MICROSOFT_APP_ID", "")
app_password = os.getenv("MICROSOFT_APP_PASSWORD", "")

logger.info(f"Bot starting with App ID: {app_id[:10]}..." if app_id else "No App ID")

SETTINGS = BotFrameworkAdapterSettings(app_id, app_password)
ADAPTER = BotFrameworkAdapter(SETTINGS)

app = Flask(__name__)

# Хэрэглэгчийн conversation reference хадгалах directory үүсгэх
CONVERSATION_DIR = "conversations"
LEAVE_REQUESTS_DIR = "leave_requests"
PENDING_CONFIRMATIONS_DIR = "pending_confirmations"

for directory in [CONVERSATION_DIR, LEAVE_REQUESTS_DIR, PENDING_CONFIRMATIONS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

def get_dynamic_manager_id(requester_email: str) -> str:
    """Хэрэглэгчийн manager-ийн ID-г dynamic байдлаар авах"""
    if not LEADER_AVAILABLE:
        logger.warning("Leader module not available, cannot get manager ID")
        return None
    
    try:
        manager_id = get_user_manager_id(requester_email)
        if manager_id:
            logger.info(f"Found dynamic manager ID for {requester_email}: {manager_id}")
            return manager_id
        else:
            logger.warning(f"No manager found for {requester_email}")
            return None
    except Exception as e:
        logger.error(f"Error getting dynamic manager ID for {requester_email}: {str(e)}")
        return None

def get_dynamic_manager_info(requester_email: str) -> Optional[Dict]:
    """Хэрэглэгчийн manager-ийн бүх мэдээллийг авах"""
    if not LEADER_AVAILABLE:
        logger.warning("Leader module not available, cannot get manager info")
        return None
    
    try:
        manager_info = get_user_manager_info(requester_email)
        if manager_info:
            logger.info(f"Found dynamic manager info for {requester_email}: {manager_info.get('displayName', 'Unknown')}")
            return manager_info
        else:
            logger.warning(f"No manager info found for {requester_email}")
            return None
    except Exception as e:
        logger.error(f"Error getting dynamic manager info for {requester_email}: {str(e)}")
        return None

def get_available_manager_id(requester_email: str, leave_days: int = 0) -> Optional[str]:
    """Чөлөөний хугацаанаас хамааран тохирох manager-ийг олох функц"""
    if not LEADER_AVAILABLE:
        logger.warning("Leader module not available, cannot get available manager")
        return None
    
    try:
        # Чөлөөний хугацаанаас хамааран manager тодорхойлох
        if leave_days >= 4:
            # 4 хоног ба түүнээс дээш бол CEO руу илгээх
            logger.info(f"Leave days: {leave_days} >= 4, sending to CEO")
            ceo_info = get_ceo_info()
            if ceo_info:
                ceo_email = ceo_info.get('mail')
                if ceo_email:
                    # CEO-ийн conversation ID олох
                    ceo_user_id = get_ceo_conversation_id(ceo_email)
                    if ceo_user_id:
                        logger.info(f"Found CEO user ID: {ceo_user_id}")
                        return ceo_user_id
                    else:
                        logger.warning(f"CEO conversation ID not found for {ceo_email}")
                        # CEO-ийн conversation ID олдохгүй бол CEO-ийн ID-г буцаах
                        return ceo_info.get('id')
                else:
                    logger.warning("CEO email not found")
            else:
                logger.warning("CEO not found, falling back to regular manager")
        
        # 3 хоног ба түүнээс доош бол эхлээд хэрэглэгчийн manager-ийг олох
        logger.info(f"Leave days: {leave_days} < 4, sending to regular manager")
        manager_info = get_user_manager_info(requester_email)
        if not manager_info:
            logger.warning(f"No manager found for {requester_email}")
            return None
        
        manager_email = manager_info.get('mail')
        if not manager_email:
            logger.warning(f"No email found for manager of {requester_email}")
            return None
        
        # Manager-ийн чөлөөний статусыг шалгах
        manager_leave_status = check_manager_leave_status(manager_email)
        
        if manager_leave_status.get('is_on_leave', False):
            logger.info(f"Manager {manager_email} is on leave, checking their manager")
            
            # Manager-ийн manager-ийг олох
            manager_manager_info = get_user_manager_info(manager_email)
            if manager_manager_info:
                manager_manager_email = manager_manager_info.get('mail')
                if manager_manager_email:
                    # Manager-ийн manager-ийн conversation ID олох
                    manager_manager_user_id = get_manager_conversation_id_by_email(manager_manager_email)
                    if manager_manager_user_id:
                        logger.info(f"Found manager's manager conversation ID: {manager_manager_user_id}")
                        return manager_manager_user_id
                    else:
                        logger.warning(f"Manager's manager conversation ID not found for {manager_manager_email}")
                        return manager_manager_info.get('id')
                else:
                    logger.warning(f"No email found for manager's manager")
                    return manager_manager_info.get('id')
            else:
                logger.warning(f"No manager found for manager {manager_email}")
                return None
        else:
            # Manager чөлөө авсангүй байна
            logger.info(f"Manager {manager_email} is available")
            
            # Manager-ийн conversation ID олох
            manager_user_id = get_manager_conversation_id_by_email(manager_email)
            if manager_user_id:
                logger.info(f"Found manager conversation ID: {manager_user_id}")
                return manager_user_id
            else:
                logger.warning(f"Manager conversation ID not found for {manager_email}, using manager ID")
                return manager_info.get('id')
            
    except Exception as e:
        logger.error(f"Error getting available manager for {requester_email}: {str(e)}")
        return None

def check_manager_leave_status(manager_email: str) -> Dict:
    """Manager-ийн чөлөөний статусыг шалгах"""
    try:
        # Хадгалагдсан leave request файлуудаас шалгах
        if os.path.exists(LEAVE_REQUESTS_DIR):
            current_date = datetime.now().date()
            
            for filename in os.listdir(LEAVE_REQUESTS_DIR):
                if filename.startswith("request_") and filename.endswith(".json"):
                    file_path = os.path.join(LEAVE_REQUESTS_DIR, filename)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            request_data = json.load(f)
                        
                        # Энэ manager-ийн чөлөөний хүсэлт эсэхийг шалгах
                        if (request_data.get('requester_email') == manager_email and 
                            request_data.get('status') == 'approved'):
                            
                            start_date = datetime.strptime(request_data.get('start_date'), '%Y-%m-%d').date()
                            end_date = datetime.strptime(request_data.get('end_date'), '%Y-%m-%d').date()
                            
                            # Чөлөөний хугацаанд байгаа эсэхийг шалгах
                            if start_date <= current_date <= end_date:
                                return {
                                    'is_on_leave': True,
                                    'start_date': request_data.get('start_date'),
                                    'end_date': request_data.get('end_date'),
                                    'reason': request_data.get('reason'),
                                    'request_id': request_data.get('request_id')
                                }
                    except Exception as e:
                        logger.error(f"Error reading leave request file {filename}: {str(e)}")
                        continue
        
        # Чөлөө авсангүй байна
        return {'is_on_leave': False}
        
    except Exception as e:
        logger.error(f"Error checking manager leave status for {manager_email}: {str(e)}")
        return {'is_on_leave': False}

def get_ceo_info() -> Optional[Dict]:
    """CEO-ийн мэдээллийг авах"""
    if not JOBTITLE_AVAILABLE:
        logger.warning("Jobtitle module not available, cannot get CEO info")
        return None
    
    try:
        # Microsoft Graph access token авах
        access_token = get_graph_access_token()
        if not access_token:
            logger.error("Microsoft Graph access token авч чадсангүй")
            return None
        
        # JobTitleAPI ашиглаж CEO хайх
        job_api = JobTitleAPI(access_token)
        
        # CEO-г хайх (олон нэрээр оролдох)
        ceo_titles = [
            "Chief Executive Officer",
            "CEO",
            "Гүйцэтгэх захирал",
            "Ерөнхий захирал"
        ]
        
        for title in ceo_titles:
            ceo_users = job_api.search_users_by_job_title(title)
            if ceo_users:
                # Зөвхөн идэвхтэй хэрэглэгчдийг шүүх
                active_ceo = [user for user in ceo_users if user.get('accountEnabled', True)]
                if active_ceo:
                    ceo = active_ceo[0]  # Эхний CEO-г авах
                    logger.info(f"Found CEO: {ceo.get('displayName')} ({ceo.get('mail')})")
                    return ceo
        
        # Хэрэв тодорхой нэрээр олдохгүй бол хэсэгчилсэн хайлт хийх
        for title in ["CEO", "Chief", "Гүйцэтгэх", "Ерөнхий"]:
            ceo_users = job_api.search_users_by_partial_job_title(title)
            if ceo_users:
                active_ceo = [user for user in ceo_users if user.get('accountEnabled', True)]
                if active_ceo:
                    ceo = active_ceo[0]
                    logger.info(f"Found CEO by partial search: {ceo.get('displayName')} ({ceo.get('mail')})")
                    return ceo
        
        logger.warning("CEO олдсонгүй")
        return None
        
    except Exception as e:
        logger.error(f"Error getting CEO info: {str(e)}")
        return None

def get_ceo_conversation_id(ceo_email: str) -> Optional[str]:
    """CEO-ийн и-мэйлээр conversation ID олох"""
    try:
        # Хадгалагдсан хэрэглэгчдийн файлуудаас CEO-г хайх
        if os.path.exists(CONVERSATION_DIR):
            for filename in os.listdir(CONVERSATION_DIR):
                if filename.startswith("user_") and filename.endswith(".json"):
                    file_path = os.path.join(CONVERSATION_DIR, filename)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            user_info = json.load(f)
                        
                        # CEO-ийн и-мэйлтэй таарч байгаа эсэхийг шалгах
                        if user_info.get('email') == ceo_email:
                            user_id = user_info.get('user_id')
                            if user_id:
                                logger.info(f"Found CEO conversation ID: {user_id}")
                                return user_id
                    except Exception as e:
                        logger.error(f"Error reading user file {filename}: {str(e)}")
                        continue
        
        logger.warning(f"CEO conversation ID not found for email: {ceo_email}")
        return None
        
    except Exception as e:
        logger.error(f"Error getting CEO conversation ID: {str(e)}")
        return None

def get_manager_conversation_id_by_email(manager_email: str) -> Optional[str]:
    """Manager-ийн и-мэйлээр conversation ID олох"""
    try:
        # Хадгалагдсан хэрэглэгчдийн файлуудаас manager-г хайх
        if os.path.exists(CONVERSATION_DIR):
            for filename in os.listdir(CONVERSATION_DIR):
                if filename.startswith("user_") and filename.endswith(".json"):
                    file_path = os.path.join(CONVERSATION_DIR, filename)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            user_info = json.load(f)
                        
                        # Manager-ийн и-мэйлтэй таарч байгаа эсэхийг шалгах
                        if user_info.get('email') == manager_email:
                            user_id = user_info.get('user_id')
                            if user_id:
                                logger.info(f"Found manager conversation ID by email: {user_id} for {manager_email}")
                                return user_id
                    except Exception as e:
                        logger.error(f"Error reading user file {filename}: {str(e)}")
                        continue
        
        logger.warning(f"Manager conversation ID not found for email: {manager_email}")
        return None
        
    except Exception as e:
        logger.error(f"Error getting manager conversation ID by email: {str(e)}")
        return None

# Timeout механизм - 30 минут = 1800 секунд
CONFIRMATION_TIMEOUT_SECONDS = 30 * 60  # 30 минут
active_timers = {}  # user_id -> Timer object

# Manager хариу өгөх timeout - 2 цаг = 7200 секунд
MANAGER_RESPONSE_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 цаг
manager_pending_actions = {}  # request_id -> Timer object

# Microsoft Graph API Configuration
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

_cached_graph_token = None
_graph_token_expiry = 0  # UNIX timestamp

def get_graph_access_token() -> str:
    """Microsoft Graph API-ын access token авах"""
    global _cached_graph_token, _graph_token_expiry

    # Хэрвээ token хүчинтэй байвал cache-аас буцаана
    if _cached_graph_token and time.time() < _graph_token_expiry - 10:
        return _cached_graph_token

    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    headers = { "Content-Type": "application/x-www-form-urlencoded" }
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }

    try:
        response = requests.post(url, headers=headers, data=data)
        if response.status_code != 200:
            logger.error(f"Microsoft Graph access token авахад алдаа: {response.status_code} - {response.text}")
            raise Exception("Microsoft Graph access token авахад амжилтгүй боллоо")

        token_data = response.json()
        _cached_graph_token = token_data["access_token"]
        _graph_token_expiry = time.time() + token_data.get("expires_in", 3600)

        logger.info("Microsoft Graph access token амжилттай авлаа")
        return _cached_graph_token
    except Exception as e:
        logger.error(f"Microsoft Graph access token авахад алдаа: {str(e)}")
        return None

class MicrosoftUsersAPI:
    """Microsoft Graph API ашиглан хэрэглэгчдийг удирдах класс"""
    
    def __init__(self, access_token: str):
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    def search_users_by_job_title(self, job_title: str) -> List[Dict]:
        """Албан тушаалаар хэрэглэгч хайх"""
        try:
            encoded_job_title = quote(job_title)
            url = f"{self.base_url}/users?$select=id,displayName,mail,jobTitle,department,accountEnabled&$filter=jobTitle eq '{encoded_job_title}'"
            
            response = requests.get(url, headers=self.headers)
            
            if response.status_code != 200:
                logger.error(f"Microsoft Graph API хэрэглэгч хайхад алдаа: {response.status_code} - {response.text}")
                return []
            
            users = response.json().get("value", [])
            # Зөвхөн идэвхтэй хэрэглэгчдийг буцаах
            active_users = [user for user in users if user.get('accountEnabled', True)]
            
            logger.info(f"'{job_title}' албан тушаалтай {len(active_users)} идэвхтэй хэрэглэгч олдлоо")
            return active_users
            
        except Exception as e:
            logger.error(f"Microsoft Graph API хэрэглэгч хайхад алдаа: {str(e)}")
            return []

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """И-мэйлээр хэрэглэгч олох"""
        try:
            encoded_email = quote(email)
            url = f"{self.base_url}/users/{encoded_email}?$select=id,displayName,mail,jobTitle,department,accountEnabled"
            
            response = requests.get(url, headers=self.headers)
            
            if response.status_code != 200:
                logger.error(f"Microsoft Graph API и-мэйлээр хэрэглэгч олоход алдаа: {response.status_code} - {response.text}")
                return None
            
            return response.json()
        except Exception as e:
            logger.error(f"Microsoft Graph API и-мэйлээр хэрэглэгч олоход алдаа: {str(e)}")
            return None

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """ID-аар хэрэглэгч олох"""
        try:
            # Teams-ийн conversation ID (ихэвчлэн "29:") эсвэл AAD GUID биш утгыг Graph-д бүү явуул
            def _is_valid_guid(value: str) -> bool:
                try:
                    _uuid_for_validation.UUID(value)
                    return True
                except Exception:
                    return False

            if not user_id or user_id.startswith("29:") or not _is_valid_guid(user_id):
                logger.warning(f"Graph get_user_by_id-д буусан user_id хүчинтэй GUID биш тул алгаслаа: {user_id}")
                return None

            url = f"{self.base_url}/users/{user_id}?$select=id,displayName,mail,jobTitle,department,accountEnabled"
            
            response = requests.get(url, headers=self.headers)
            
            if response.status_code != 200:
                logger.error(f"Microsoft Graph API ID-аар хэрэглэгч олоход алдаа: {response.status_code} - {response.text}")
                return None
            
            return response.json()
        except Exception as e:
            logger.error(f"Microsoft Graph API ID-аар хэрэглэгч олоход алдаа: {str(e)}")
            return None

    def assign_sponsor_to_user(self, user_id: str, sponsor_id: str) -> bool:
        """Guest user-д sponsor (орлон ажиллах хүн) томилох"""
        try:
            # Эхлээд одоогийн sponsor-уудыг шалгах
            existing_sponsors = self.get_user_sponsors(user_id)
            
            # Sponsor аль хэдийн байгаа эсэхийг шалгах
            for sponsor in existing_sponsors:
                if sponsor.get('id') == sponsor_id:
                    logger.info(f"Sponsor аль хэдийн томилогдсон байна: {sponsor.get('displayName')}")
                    return True  # Аль хэдийн томилогдсон байгаа тул success гэж тооцно
            
            url = f"{self.base_url}/users/{user_id}/sponsors/$ref"
            
            data = {
                "@odata.id": f"https://graph.microsoft.com/v1.0/users/{sponsor_id}"
            }
            
            response = requests.post(url, headers=self.headers, json=data)
            
            if response.status_code in [200, 204]:
                logger.info(f"Sponsor амжилттай томилогдлоо: {user_id} -> {sponsor_id}")
                return True
            elif response.status_code == 400 and "already exist" in response.text:
                logger.info(f"Sponsor аль хэдийн томилогдсон байна: {user_id} -> {sponsor_id}")
                return True  # Аль хэдийн томилогдсон байгаа тул success гэж тооцно
            else:
                logger.error(f"Sponsor томилоход алдаа: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Sponsor томилоход алдаа: {str(e)}")
            return False

    def get_user_sponsors(self, user_id: str) -> List[Dict]:
        """Хэрэглэгчийн sponsor-уудыг авах"""
        try:
            url = f"{self.base_url}/users/{user_id}/sponsors"
            
            response = requests.get(url, headers=self.headers)
            
            if response.status_code != 200:
                logger.error(f"Sponsor мэдээлэл авахад алдаа: {response.status_code} - {response.text}")
                return []
            
            return response.json().get("value", [])
        except Exception as e:
            logger.error(f"Sponsor мэдээлэл авахад алдаа: {str(e)}")
            return []

    def remove_sponsor_from_user(self, user_id: str, sponsor_id: str) -> bool:
        """Хэрэглэгчээс sponsor хасах"""
        try:
            url = f"{self.base_url}/users/{user_id}/sponsors/{sponsor_id}/$ref"
            
            response = requests.delete(url, headers=self.headers)
            
            if response.status_code in [200, 204]:
                logger.info(f"Sponsor амжилттай хасагдлаа: {user_id} -> {sponsor_id}")
                return True
            else:
                logger.error(f"Sponsor хасахад алдаа: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Sponsor хасахад алдаа: {str(e)}")
            return False

def assign_replacement_worker(requester_email: str, replacement_email: str) -> Dict:
    """Чөлөө авсан хүнд орлон ажиллах хүн томилох"""
    try:
        access_token = get_graph_access_token()
        if not access_token:
            return {"success": False, "message": "Microsoft Graph access token авч чадсангүй"}
        
        users_api = MicrosoftUsersAPI(access_token)
        
        # Чөлөө авсан хүнийг олох
        requester = users_api.get_user_by_email(requester_email)
        if not requester:
            return {"success": False, "message": f"Чөлөө авсан хүн олдсонгүй: {requester_email}"}
        
        # Орлон ажиллах хүнийг олох
        replacement = users_api.get_user_by_email(replacement_email)
        if not replacement:
            return {"success": False, "message": f"Орлон ажиллах хүн олдсонгүй: {replacement_email}"}
        
        # Sponsor томилох
        success = users_api.assign_sponsor_to_user(requester.get('id'), replacement.get('id'))
        
        if success:
            logger.info(f"Орлон ажиллах хүн томилогдлоо: {requester_email} -> {replacement_email}")
            
            # Таскуудыг sponsor дээр шилжүүлэх
            task_transfer_message = ""
            try:
                task_manager = TaskAssignmentManager(get_cached_access_token())
                transfer_result = task_manager.transfer_all_tasks(requester_email, replacement_email)
                
                if transfer_result:
                    task_transfer_message = "Таскууд амжилттай шилжүүлэгдлээ"
                    logger.info(f"Таскууд шилжүүлэгдлээ: {requester_email} -> {replacement_email}")
                else:
                    task_transfer_message = "Таск шилжүүлэхэд алдаа гарлаа эсвэл шилжүүлэх таск байхгүй"
                    logger.warning(f"Таск шилжүүлэхэд алдаа: {requester_email} -> {replacement_email}")
            except Exception as task_error:
                task_transfer_message = f"Таск шилжүүлэхэд алдаа гарлаа: {str(task_error)}"
                logger.error(f"Таск шилжүүлэх алдаа: {str(task_error)}")
            
            return {
                "success": True,
                "message": f"Орлон ажиллах хүн амжилттай томилогдлоо. {task_transfer_message}",
                "requester": {
                    "id": requester.get('id'),
                    "name": requester.get('displayName'),
                    "email": requester.get('mail')
                },
                "replacement": {
                    "id": replacement.get('id'),
                    "name": replacement.get('displayName'),
                    "email": replacement.get('mail')
                },
                "task_transfer": task_transfer_message
            }
        else:
            return {"success": False, "message": "Sponsor томилоход алдаа гарлаа"}
            
    except Exception as e:
        logger.error(f"Орлон ажиллах хүн томилоход алдаа: {str(e)}")
        return {"success": False, "message": str(e)}

def remove_replacement_worker(requester_email: str, replacement_email: str) -> Dict:
    """Чөлөө авсан хүнээс орлон ажиллах хүнийг хасах"""
    try:
        access_token = get_graph_access_token()
        if not access_token:
            return {"success": False, "message": "Microsoft Graph access token авч чадсангүй"}
        
        users_api = MicrosoftUsersAPI(access_token)
        
        # Чөлөө авсан хүнийг олох
        requester = users_api.get_user_by_email(requester_email)
        if not requester:
            return {"success": False, "message": f"Чөлөө авсан хүн олдсонгүй: {requester_email}"}
        
        # Орлон ажиллах хүнийг олох
        replacement = users_api.get_user_by_email(replacement_email)
        if not replacement:
            return {"success": False, "message": f"Орлон ажиллах хүн олдсонгүй: {replacement_email}"}
        
        # Sponsor хасах
        success = users_api.remove_sponsor_from_user(requester.get('id'), replacement.get('id'))
        
        if success:
            logger.info(f"Орлон ажиллах хүн хасагдлаа: {requester_email} -> {replacement_email}")
            
            # Таскуудыг эх хэрэглэгч рүү буцаан шилжүүлэх
            task_transfer_message = ""
            try:
                task_manager = TaskAssignmentManager(get_cached_access_token())
                transfer_result = task_manager.transfer_all_tasks(replacement_email, requester_email)
                
                if transfer_result:
                    task_transfer_message = "Таскууд эх хэрэглэгч рүү буцаан шилжүүлэгдлээ"
                    logger.info(f"Таскууд буцаан шилжүүлэгдлээ: {replacement_email} -> {requester_email}")
                else:
                    task_transfer_message = "Таск буцаан шилжүүлэхэд алдаа гарлаа эсвэл шилжүүлэх таск байхгүй"
                    logger.warning(f"Таск буцаан шилжүүлэхэд алдаа: {replacement_email} -> {requester_email}")
            except Exception as task_error:
                task_transfer_message = f"Таск буцаан шилжүүлэхэд алдаа гарлаа: {str(task_error)}"
                logger.error(f"Таск буцаан шилжүүлэх алдаа: {str(task_error)}")
            
            return {
                "success": True,
                "message": f"Орлон ажиллах хүн амжилттай хасагдлаа. {task_transfer_message}",
                "requester": {
                    "id": requester.get('id'),
                    "name": requester.get('displayName'),
                    "email": requester.get('mail')
                },
                "replacement": {
                    "id": replacement.get('id'),
                    "name": replacement.get('displayName'),
                    "email": replacement.get('mail')
                },
                "task_transfer": task_transfer_message
            }
        else:
            return {"success": False, "message": "Sponsor хасахад алдаа гарлаа"}
            
    except Exception as e:
        logger.error(f"Орлон ажиллах хүн хасахад алдаа: {str(e)}")
        return {"success": False, "message": str(e)}

def get_replacement_workers(requester_email: str) -> Dict:
    """Чөлөө авсан хүний орлон ажиллах хүмүүсийг авах"""
    try:
        access_token = get_graph_access_token()
        if not access_token:
            return {"success": False, "message": "Microsoft Graph access token авч чадсангүй"}
        
        users_api = MicrosoftUsersAPI(access_token)
        
        # Чөлөө авсан хүнийг олох
        requester = users_api.get_user_by_email(requester_email)
        if not requester:
            return {"success": False, "message": f"Чөлөө авсан хүн олдсонгүй: {requester_email}"}
        
        # Sponsor-уудыг авах
        sponsors = users_api.get_user_sponsors(requester.get('id'))
        
        replacement_workers = []
        for sponsor in sponsors:
            replacement_workers.append({
                "id": sponsor.get('id'),
                "name": sponsor.get('displayName'),
                "email": sponsor.get('mail'),
                "jobTitle": sponsor.get('jobTitle')
            })
        
        return {
            "success": True,
            "requester": {
                "id": requester.get('id'),
                "name": requester.get('displayName'),
                "email": requester.get('mail')
            },
            "replacement_workers": replacement_workers,
            "count": len(replacement_workers)
        }
        
    except Exception as e:
        logger.error(f"Орлон ажиллах хүмүүсийг авахад алдаа: {str(e)}")
        return {"success": False, "message": str(e)}

def auto_remove_replacement_workers_on_leave_end(requester_email: str) -> Dict:
    """Чөлөө дуусахад орлон ажиллах хүмүүсийг автоматаар хасах"""
    try:
        # Орлон ажиллах хүмүүсийг авах
        result = get_replacement_workers(requester_email)
        if not result["success"]:
            return result
        
        replacement_workers = result["replacement_workers"]
        if not replacement_workers:
            return {"success": True, "message": "Хасах орлон ажиллах хүн байхгүй", "removed_count": 0}
        
        removed_count = 0
        errors = []
        task_transfer_messages = []
        
        # Бүх орлон ажиллах хүмүүсийг хасах
        for replacement in replacement_workers:
            remove_result = remove_replacement_worker(requester_email, replacement["email"])
            if remove_result["success"]:
                removed_count += 1
                logger.info(f"Автомат хасагдлаа: {replacement['name']} ({replacement['email']})")
                
                # Таск шилжүүлэх мэдээллийг нэмэх
                if "task_transfer" in remove_result:
                    task_transfer_messages.append(f"{replacement['name']}: {remove_result['task_transfer']}")
            else:
                errors.append(f"{replacement['name']}: {remove_result['message']}")
        
        # Таск шилжүүлэх мэдээллийг нэгтгэх
        task_summary = ""
        if task_transfer_messages:
            task_summary = " Таск шилжүүлэлт: " + "; ".join(task_transfer_messages)
        
        return {
            "success": True,
            "message": f"{removed_count} орлон ажиллах хүн автоматаар хасагдлаа{task_summary}",
            "removed_count": removed_count,
            "total_count": len(replacement_workers),
            "errors": errors,
            "task_transfers": task_transfer_messages
        }
        
    except Exception as e:
        logger.error(f"Автомат орлон ажиллах хүн хасахад алдаа: {str(e)}")
        return {"success": False, "message": str(e)}

async def check_and_cleanup_expired_leaves():
    """Дууссан чөлөөний орлон ажиллах хүмүүсийг автоматаар цэвэрлэх"""
    try:
        from datetime import datetime
        import os
        import glob
        
        current_date = datetime.now().date()
        cleanup_results = []
        
        # Хадгалагдсан бүх leave request файлуудыг шалгах
        if os.path.exists(LEAVE_REQUESTS_DIR):
            for file_path in glob.glob(f"{LEAVE_REQUESTS_DIR}/request_*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        request_data = json.load(f)
                    
                    end_date_str = request_data.get('end_date')
                    requester_email = request_data.get('requester_email')
                    request_status = request_data.get('status')
                    
                    if not end_date_str or not requester_email or request_status != 'approved':
                        continue
                    
                    # End date-г parse хийх
                    try:
                        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                    except ValueError:
                        continue
                    
                    # Чөлөө дууссан эсэхийг шалгах
                    if end_date < current_date:
                        logger.info(f"Дууссан чөлөө олдлоо: {requester_email} ({end_date})")
                        
                        # Орлон ажиллах хүмүүсийг автомат хасах
                        result = auto_remove_replacement_workers_on_leave_end(requester_email)
                        
                        # Чөлөө дуусахад таскуудыг автоматаар unassign хийх
                        task_unassign_result = await unassign_tasks_on_leave_end(requester_email)
                        if task_unassign_result:
                            result["task_unassign"] = task_unassign_result
                        
                        cleanup_results.append({
                            "requester_email": requester_email,
                            "end_date": end_date_str,
                            "result": result
                        })
                        
                        # Leave request-н статусыг 'completed' болгох
                        request_data['status'] = 'completed'
                        request_data['completed_at'] = datetime.now().isoformat()
                        request_data['auto_cleanup'] = True
                        
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(request_data, f, ensure_ascii=False, indent=2)
                        
                        logger.info(f"Leave request completed: {requester_email}")
                
                except Exception as e:
                    logger.error(f"Leave request файл боловсруулахад алдаа {file_path}: {str(e)}")
                    continue
        
        logger.info(f"Expired leaves cleanup completed: {len(cleanup_results)} processed")
        return {
            "success": True,
            "message": f"{len(cleanup_results)} дууссан чөлөө боловсруулагдлаа",
            "processed_count": len(cleanup_results),
            "results": cleanup_results
        }
        
    except Exception as e:
        logger.error(f"Expired leaves cleanup-д алдаа: {str(e)}")
        return {"success": False, "message": str(e)}

def get_hr_managers() -> List[Dict]:
    """HR Manager-уудын жагсаалтыг авах (зөвхөн timeout үед ашиглах)"""
    try:
        access_token = get_graph_access_token()
        if not access_token:
            logger.error("Microsoft Graph access token авч чадсангүй")
            return []
        
        users_api = MicrosoftUsersAPI(access_token)
        hr_managers = users_api.search_users_by_job_title("Human Resource Manager")
        
        return hr_managers
    except Exception as e:
        logger.error(f"HR Manager-уудыг олоход алдаа: {str(e)}")
        return []

def get_all_users_choices():
    """Бүх хэрэглэгчдийн жагсаалтыг ChoiceSet-д зориулж форматлах"""
    if not ALL_USERS_AVAILABLE:
        logger.warning("All users module not available")
        return []
    
    try:
        # Access token авах
        token = get_access_token()
        if not token:
            logger.error("Access token авч чадсангүй")
            return []
        
        # Бүх хэрэглэгчдийн мэдээлэл авах
        users_api = AllUsersAPI(token)
        users = users_api.get_all_users()
        
        # ChoiceSet-д зориулж форматлах
        choices = []
        for user in users:
            name = user.get("displayName", "Нэргүй")
            email = user.get("mail") or user.get("userPrincipalName", "")
            job_title = user.get("jobTitle", "")
            department = user.get("department", "")
            
            # Хэрэглэгчийн мэдээллийг title-д харуулах
            title = f"{name} - {job_title}"
            # if department:
            #     title += f" ({department})"
            
            choices.append({
                "title": title,
                "value": email
            })
        
        logger.info(f"Бүх хэрэглэгчдийн жагсаалт бэлтгэгдлээ: {len(choices)} хэрэглэгч")
        return choices
        
    except Exception as e:
        logger.error(f"Хэрэглэгчдийн жагсаалт авахад алдаа: {str(e)}")
        return []

def create_approval_card(request_data):
    """Approval-ын тулд adaptive card үүсгэх - tasks-уудтай"""
    
    # Хэрэглэгчийн tasks авах
    requester_email = request_data.get("requester_email")
    tasks_section = []
    
    if requester_email and PLANNER_AVAILABLE:
        try:
            token = get_graph_access_token()
            planner_api = MicrosoftPlannerTasksAPI(token)
            tasks = planner_api.get_user_tasks(requester_email)
            
            if tasks:
                # Зөвхөн идэвхтэй (дуусаагүй) tasks харуулах
                active_tasks = [task for task in tasks if task.get('percentComplete', 0) < 100]
                
                if active_tasks:
                    # Tasks хэсэг нэмэх
                    tasks_section.extend([
                        {
                            "type": "TextBlock",
                            "text": "📋 **Дутуу даалгаврууд (орлон ажиллах хүнд шилжүүлэх):**",
                            "wrap": True,
                            "weight": "bolder",
                            "spacing": "medium"
                        }
                    ])
                    
                    # Зөвхөн эхний 5 tasks харуулах
                    for i, task in enumerate(active_tasks[:5], 1):
                        title = task.get('title', 'Нэргүй task')
                        task_id = task.get('id', '')
                        priority = task.get('priority', 'normal')
                        # Таскын URL
                        task_url = None
                        try:
                            task_url = planner_api.generate_task_url(task_id)
                        except Exception:
                            task_url = None
                        
                        # Due date форматлах
                        due_date = task.get('dueDateTime')
                        due_text = ""
                        if due_date:
                            try:
                                dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                                due_text = f" 📅 {dt.strftime('%m/%d')}"
                            except:
                                due_text = f" 📅 {due_date[:10]}"
                        
                        priority_emoji = "🔴" if priority == "urgent" else "🟡" if priority == "important" else "🔵"
                        
                        # Гарын үсэгтэй гарчигийг линк болгох
                        link_text = f"{i}. {priority_emoji} "
                        if task_url:
                            link_text += f"[{title}]({task_url}){due_text}"
                        else:
                            link_text += f"{title}{due_text}"

                        # Клик хийж нээх линктэй мөр
                        tasks_section.append({
                            "type": "TextBlock",
                            "text": link_text,
                            "wrap": True
                        })

                        # Сонголтын toggle (даралгүйгээр линк дээр дарж нээнэ)
                        tasks_section.append({
                            "type": "Input.Toggle",
                            "id": f"task_{task_id}",
                            "title": "Шилжүүлэхээр сонгох",
                            "value": "false",
                            "valueOn": "true",
                            "valueOff": "false"
                        })
                    
                    if len(active_tasks) > 5:
                        tasks_section.append({
                            "type": "TextBlock",
                            "text": f"... болон {len(active_tasks) - 5} бусад task",
                            "isSubtle": True,
                            "spacing": "small"
                        })
                else:
                    tasks_section.append({
                        "type": "TextBlock",
                        "text": "📋 Дутуу даалгавар олдсонгүй",
                        "isSubtle": True,
                        "spacing": "medium"
                    })
            else:
                tasks_section.append({
                    "type": "TextBlock",
                    "text": "📋 Planner tasks олдсонгүй",
                    "isSubtle": True,
                    "spacing": "medium"
                })
        except Exception as e:
            logger.error(f"Failed to get tasks for approval card: {str(e)}")
            tasks_section.append({
                "type": "TextBlock",
                "text": f"📋 Tasks авахад алдаа: {str(e)}",
                "isSubtle": True,
                "spacing": "medium"
            })
    else:
        tasks_section.append({
            "type": "TextBlock",
            "text": "📋 Planner модуль идэвхгүй байна",
            "isSubtle": True,
            "spacing": "medium"
        })
    
    card = {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "🏖️ Чөлөөний хүсэлт",
                "weight": "bolder",
                "size": "large",
                "color": "accent"
            },
            {
                "type": "FactSet",
                "facts": [
                    {
                        "title": "Хүсэлт гаргагч:",
                        "value": request_data.get("requester_name", "N/A")
                    },
                    {
                        "title": "Эхлэх өдөр:",
                        "value": request_data.get("start_date", "N/A")
                    },
                    {
                        "title": "Дуусах өдөр:",
                        "value": request_data.get("end_date", "N/A")
                    },
                    {
                        "title": "Хоногийн тоо:",
                        "value": str(request_data.get("days", "N/A"))
                    },
                    {
                        "title": "Цагийн тоо:",
                        "value": f"{request_data.get('inactive_hours', 'N/A')} цаг"
                    },
                    {
                        "title": "Шалтгаан:",
                        "value": request_data.get("reason", "Тодорхойгүй")
                    }
                ]
            }
        ] + tasks_section + [
            {
                "type": "TextBlock",
                "text": "🔄 **Орлон ажиллах хүн томилох (сонголттой):**",
                "wrap": True,
                "weight": "bolder",
                "spacing": "medium"
            },
            {
                "type": "Input.ChoiceSet",
                "id": "replacement_email",
                "placeholder": "Орлон ажиллах хүнийг сонгоно уу...",
                "choices": get_all_users_choices(),
                "isRequired": False
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Зөвшөөрөх",
                "data": {
                    "action": "approve",
                    "request_id": request_data.get("request_id")
                },
                "style": "positive"
            },
            {
                "type": "Action.Submit", 
                "title": "❌ Татгалзах",
                "data": {
                    "action": "reject",
                    "request_id": request_data.get("request_id")
                },
                "style": "destructive"
            }
        ]
    }
    return card

def get_user_planner_tasks(user_email):
    """Хэрэглэгчийн Microsoft Planner tasks авах"""
    if not PLANNER_AVAILABLE:
        return "📋 Planner модуль идэвхгүй байна"
    
    try:
        # Access token авах
        token = get_access_token()
        planner_api = MicrosoftPlannerTasksAPI(token)
        
        # Хэрэглэгчийн tasks авах
        tasks = planner_api.get_user_tasks(user_email)
        
        if not tasks:
            return "📋 Planner-д идэвхтэй task олдсонгүй"
        
        # Tasks-ийн мэдээллийг форматлах
        # tasks_info = f"📋 **{user_email} - Planner Tasks:**\n\n"
        # tasks_info = f"📋 **{user_email} - Planner Tasks ({len(tasks)} task):**\n\n"
        
        # Зөвхөн идэвхтэй (дуусаагүй) tasks харуулах
        active_tasks = [task for task in tasks if task.get('percentComplete', 0) < 100]
        
        if not active_tasks:
            return "📋 Planner-д дуусаагүй task олдсонгүй"
        
        tasks_info = ""
        for i, task in enumerate(active_tasks[:5], 1):  # Зөвхөн эхний 5-г харуулах
            title = task.get('title', 'Нэргүй task')
            progress = task.get('percentComplete', 0)
            priority = task.get('priority', 'N/A')
            task_id = task.get('id')

            # Due date форматлах
            due_date = task.get('dueDateTime')
            due_text = ""
            if due_date:
                try:
                    # ISO datetime парс хийх
                    dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                    due_text = f" 📅 {dt.strftime('%m/%d')}"
                except:
                    due_text = f" 📅 {due_date[:10]}"

            # Priority emoji
            priority_emoji = "🔴" if priority == "urgent" else "🟡" if priority == "important" else "🔵"

            # Таскын URL гаргаж Markdown hyperlink болгох
            task_url = None
            try:
                if task_id:
                    task_url = planner_api.generate_task_url(task_id)
            except Exception:
                task_url = None

            if task_url:
                tasks_info += f"{i}. {priority_emoji} [{title}]({task_url}){due_text}\n"
            else:
                tasks_info += f"{i}. {priority_emoji} **{title}**{due_text}\n"
        
        if len(active_tasks) > 5:
            tasks_info += f"... болон {len(active_tasks) - 5} бусад task\n"
        
        return tasks_info.strip()
        
    except Exception as e:
        logger.error(f"Failed to get planner tasks for {user_email}: {str(e)}")
        return f"📋 Planner tasks авахад алдаа: {str(e)}"

async def call_external_absence_api(request_data):
    """External API руу absence request үүсгэх дуудлага хийх"""
    try:
        # TODO: Config-оос уншдаг болгох
        api_url = os.getenv("ABSENCE_API_URL", "https://mcp-server-production-c4d1.up.railway.app/call-function")
        
        # API payload бэлтгэх
        # payload = {
        #     "function": "create_absence_request",
        #     "args": {
        #         "user_email": request_data.get("requester_email"),
        #         "start_date": request_data.get("start_date"),
        #         "end_date": request_data.get("end_date"),
        #         "reason": request_data.get("reason", ""),
        #         "in_active_hours": request_data.get("inactive_hours", 8)
        #     }
        # }
        
        # Description рүү зөвхөн хэрэглэгчийн бичсэн шалтгааныг дамжуулна, reason нь leave_type байх ёстой
        reason_text = (request_data.get("reason") or "").strip()
        leave_type = request_data.get("leave_type") or "day_off"
        inactive_hours = request_data.get("inactive_hours", 8)
        description = reason_text
        
        payload = {
            "function": "create_absence_request",
            "args": {
                "user_email": "test_user10@fibo.cloud",
                "start_date": request_data.get("start_date"),
                "end_date": request_data.get("end_date"),
                "reason": leave_type,
                "in_active_hours": inactive_hours,
                "description": description
            }
        }
        
        logger.info(f"Calling external API for absence request: {payload}")
        
        # HTTP POST дуудлага хийх
        try:
            response = requests.post(
                api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"External API connection error: {str(ce)}")
            return {
                "success": False,
                "error": "Connection error",
                "message": str(ce)
            }
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"External API success: {result}")
            logger.info(f"API Response status code: {response.status_code}")
            logger.info(f"API Response headers: {dict(response.headers)}")
            logger.info(f"Full API Response: {response.text}")
            
            # Response-аас absence_id авах оролдлого
            absence_id = None
            if isinstance(result, dict):
                # API response structure: {'result': {'absence_id': 342, ...}}
                absence_id = (result.get("result", {}).get("absence_id") or 
                             result.get("absence_id") or 
                             result.get("id") or 
                             result.get("data", {}).get("id"))
                logger.info(f"Extracted absence_id: {absence_id} from API response")
            
            return {
                "success": True,
                "data": result,
                "absence_id": absence_id,
                "message": "Absence request created successfully"
            }
        else:
            logger.error(f"External API error - Status: {response.status_code}")
            logger.error(f"API Error Response: {response.text}")
            logger.error(f"API Error Headers: {dict(response.headers)}")
            logger.error(f"Sent Payload: {payload}")
            # 404 бол fallback function нэр/зам шалгаж энгийн форматтай шинэ endpoint руу оролдох боломжтой
            return {
                "success": False,
                "error": f"API returned status {response.status_code}",
                "message": response.text,
                "payload": payload,
                "url": api_url
            }
            
    except requests.exceptions.Timeout:
        logger.error("External API timeout")
        return {
            "success": False,
            "error": "API timeout",
            "message": "External API request timed out"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"External API request error: {str(e)}")
        return {
            "success": False,
            "error": "Request failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error calling external API: {str(e)}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }

async def call_approve_absence_api(absence_id, comment="Зөвшөөрсөн"):
    """External API руу absence approve дуудлага хийх"""
    try:
        api_url = "https://mcp-server-production-6219.up.railway.app/call-function"
        
        # API payload бэлтгэх
        payload = {
            "function": "approve_absence",
            "args": {
                "absence_id": absence_id,
                "comment": comment
            }
        }
        
        logger.info(f"Calling external API for absence approval: {payload}")
        
        # HTTP POST дуудлага хийх
        response = requests.post(
            api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"External API approval success: {result}")
            return {
                "success": True,
                "data": result,
                "message": "Absence approved successfully"
            }
        else:
            logger.error(f"External API approval error - Status: {response.status_code}, Response: {response.text}")
            return {
                "success": False,
                "error": f"API returned status {response.status_code}",
                "message": response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error("External API approval timeout")
        return {
            "success": False,
            "error": "API timeout",
            "message": "External API request timed out"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"External API approval request error: {str(e)}")
        return {
            "success": False,
            "error": "Request failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error calling external approval API: {str(e)}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }

async def call_reject_absence_api(absence_id, comment=""):
    """External API руу absence reject дуудлага хийх"""
    try:
        api_url = "https://mcp-server-production-6219.up.railway.app/call-function"
        
        # API payload бэлтгэх
        payload = {
            "function": "reject_absence",
            "args": {
                "absence_id": absence_id,
                "comment": comment
            }
        }
        
        logger.info(f"Calling external API for absence rejection: {payload}")
        
        # HTTP POST дуудлага хийх
        response = requests.post(
            api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"External API rejection success: {result}")
            return {
                "success": True,
                "data": result,
                "message": "Absence rejected successfully"
            }
        else:
            logger.error(f"External API rejection error - Status: {response.status_code}, Response: {response.text}")
            return {
                "success": False,
                "error": f"API returned status {response.status_code}",
                "message": response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error("External API rejection timeout")
        return {
            "success": False,
            "error": "API timeout",
            "message": "External API request timed out"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"External API rejection request error: {str(e)}")
        return {
            "success": False,
            "error": "Request failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error calling external rejection API: {str(e)}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }
    
async def send_teams_webhook_notification(requester_name, replacement_worker_name=None, request_data=None, task_transfer_info=None):
    """Teams webhook руу зөвшөөрөлийн мэдэгдэл илгээх"""
    try:
        # Webhook URL-ийг тохиргооноос ашиглах
        webhook_url = "https://prod-36.southeastasia.logic.azure.com:443/workflows/6dcb3cbe39124404a12b754720b25699/triggers/manual/paths/invoke?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=nhqRPaYSLixFlWOePwBHVlyWrbAv6OL7h0SNclMZS0U"

        # Чөлөөний мэдээлэл задлах
        start_date = request_data.get('start_date') if request_data else None
        end_date = request_data.get('end_date') if request_data else None
        days = request_data.get('days') if request_data else None
        inactive_hours = request_data.get('inactive_hours') if request_data else None
        hour_from = request_data.get('hour_from') if request_data else None
        hour_to = request_data.get('hour_to') if request_data else None

        # Хугацааг текстжүүлэх
        duration_dates = "N/A"
        if start_date and end_date:
            duration_dates = start_date if start_date == end_date else f"{start_date} - {end_date}"

        days_suffix = f" ({days} хоног)" if isinstance(days, int) else ""

        # Цагийн чөлөө эсэхийг тодорхойлох
        is_hour_leave = False
        if inactive_hours is not None:
            try:
                is_hour_leave = float(inactive_hours) < 8
            except Exception:
                is_hour_leave = False
        if hour_from or hour_to:
            is_hour_leave = True

        # Мессежийн мөрүүд угсрах (цагийн чөлөөнд л цагийн мөрийг оруулна)
        message_lines = [
            "📢 Чөлөөний мэдээлэл",
            f"👤 Нэр: {requester_name}",
            f"📅 Хугацаа: {duration_dates}{days_suffix}",
        ]

        if is_hour_leave:
            if hour_from and hour_to and start_date and end_date and start_date == end_date and inactive_hours is not None:
                message_lines.append(f"⏰ Цаг: {hour_from} - {hour_to} ({inactive_hours} цаг)")
            elif inactive_hours is not None:
                message_lines.append(f"⏰ Цаг: {inactive_hours} цаг")

        if replacement_worker_name:
            message_lines.append(f"🔄 Орлон ажиллах: {replacement_worker_name}")

        message_lines.append("")
        message_lines.append(f"{requester_name} чөлөө авсан болохыг анхаарна уу, манайхаан.")

        message = "<br>".join(message_lines)

        # Teams webhook payload бэлтгэх
        payload = {"message": message}
        
        logger.info(f"Sending Teams webhook notification for {requester_name}")
        
        # HTTP POST дуудлага хийх
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Teams webhook notification sent successfully for {requester_name}")
            return {
                "success": True,
                "message": "Teams notification sent successfully"
            }
        else:
            logger.error(f"Teams webhook error - Status: {response.status_code}, Response: {response.text}")
            return {
                "success": False,
                "error": f"Webhook returned status {response.status_code}",
                "message": response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error("Teams webhook timeout")
        return {
            "success": False,
            "error": "Webhook timeout",
            "message": "Teams webhook request timed out"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Teams webhook request error: {str(e)}")
        return {
            "success": False,
            "error": "Request failed",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error calling Teams webhook: {str(e)}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }

def save_leave_request(request_data):
    """Чөлөөний хүсэлтийг хадгалах"""
    try:
        request_id = request_data["request_id"]
        filename = f"{LEAVE_REQUESTS_DIR}/request_{request_id}.json"
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(request_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved leave request {request_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save leave request: {str(e)}")
        return False

def load_leave_request(request_id):
    """Чөлөөний хүсэлтийг унших"""
    try:
        filename = f"{LEAVE_REQUESTS_DIR}/request_{request_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load leave request {request_id}: {str(e)}")
        return None

def is_leave_request(text):
    """Мессеж нь чөлөөний хүсэлт эсэхийг шалгах"""
    leave_keywords = [
        'чөлөө', 'амралт', 'leave', 'vacation', 'holiday',
        'чөлөөний хүсэлт', 'амралтын хүсэлт', 'чөлөө авах',
        'амрах', 'чөлөөтэй байх', 'амралтанд явах'
    ]
    
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in leave_keywords)

def parse_leave_request(text, user_name):
    """ChatGPT-4 ашиглаж чөлөөний хүсэлтийн мэдээллийг ойлгох"""
    try:
        if not openai_client.api_key:
            logger.warning("OpenAI API key not configured, falling back to simple parsing")
            return parse_leave_request_simple(text, user_name)
        
        # Өнөөдрийн огноог AI-д өгөх
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        tomorrow = today + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        
        prompt = f"""
Та чөлөөний хүсэлт боловсруулах туслах юм. Доорх мессежээс database.Absence struct-д оруулах мэдээллийг гаргаж, JSON хэлбэрээр буцаа.

ӨНӨӨДРИЙН ОГНОО: {today_str} ({today.strftime("%A")})
МАРГААШИЙН ОГНОО: {tomorrow_str} ({tomorrow.strftime("%A")})

Хэрэглэгч: {user_name}
Мессеж: "{text}"

Database schema (Go struct):
type Absence struct {{
    StartDate     time.Time
    Reason        string
    EmployeeID    uint
    InActiveHours int
    Status        string
}}

Гаргах ёстой мэдээлэл:
- start_date: Эхлэх огноо (YYYY-MM-DD формат)
- end_date: Дуусах огноо (YYYY-MM-DD формат) 
- reason: Шалтгаан (string)
- employee_id: Ажилтны ID (засвар хийх шаардлагагүй, backend дээр тохируулна)
- inactive_hours: Идэвхгүй цагийн тоо (ЦААГААР тооцоолох)
- status: Төлөв (default: "pending")
- needs_clarification: Нэмэлт мэдээлэл хэрэгтэй эсэх (true/false)
- questions: Хэрэв needs_clarification true бол асуух асуултууд

ЧУХАЛ ДҮРЭМ:
- "МАРГААШ" = {tomorrow_str}
- "ӨНӨӨДӨР" = {today_str}
- "ХОЁР ӨДРИЙН ДАРАА" = {(today + timedelta(days=2)).strftime("%Y-%m-%d")}
- "ЭНЭ ДОЛОО ХОНОГ" = одоогийн долоо хоногт
- "ДАРААГИЙН ДОЛОО ХОНОГ" = дараагийн долоо хоногт

ЦАГИЙН ТООЦООЛОЛ:
- "1 ХОНОГ" = 8 цаг
- "0.5 ХОНОГ" эсвэл "ХАГАС ХОНОГ" = 4 цаг
- "2 ЦАГ" = 2 цаг
- "3 ЦАГ" = 3 цаг
- "4 ЦАГ" = 4 цаг
- "ӨГЛӨӨний ЦАГ" эсвэл "ӨГЛӨӨ" = 4 цаг
- "ҮДЭЭС ХОЙШ" эсвэл "ҮДИЙН ЦАГ" = 4 цаг

ШАЛТГААНЫ ДҮРЭМ:
- Хувийн шалтгаанаар чөлөө авбал = "day_off"
- Өвчтэй болон эмнэлгийн чөлөө авбал = "sick"
- Хэрэв шалтгаан тодорхойгүй бол needs_clarification = true болгож "Чөлөө авах шалтгаан юу вэ?" асуулт нэмэх

ОГНООНЫ ДҮРЭМ:
- Хэрэв inactive_hours < 8 (цагийн чөлөө) бол start_date = end_date (тэр өдөр л)
- Хэрэв inactive_hours >= 8 (хоногийн чөлөө) бол end_date = start_date + (хоногийн тоо - 1)
- Хэрэв огноо тодорхойгүй бол needs_clarification = true болгож "Хэзээ чөлөө авах вэ?" асуулт нэмэх
- Хэрэв цаг/хоног тодорхойгүй бол needs_clarification = true болгож "Хэдэн хоног эсвэл цаг чөлөө авах вэ?" асуулт нэмэх
- Status үргэлж "pending" байна

НЭМЭЛТ МЭДЭЭЛЭЛ ШААРДЛАГАТАЙ ҮЕИЙН ДҮРЭМ:
- Хэрэв огноо тодорхойгүй бол needs_clarification = true
- Хэрэв цаг/хоног тодорхойгүй бол needs_clarification = true  
- Хэрэв шалтгаан тодорхойгүй бол needs_clarification = true
- Хэрэв мэдээлэл дутуу бол needs_clarification = true болгож холбогдох асуултууд нэмэх
- Асуултуудыг монгол хэл дээр, энгийн, ойлгомжтой байдлаар бичэх

ӨНӨӨДРИЙН ОГНОО ({today_str})-ийг үндэслэн тооцоол хийнэ үү!

JSON буцаа:
"""

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": f"Та чөлөөний хүсэлт боловсруулах туслах. Монгол хэл дээрх байгалийн хэлийг ойлгож, database.Absence struct-д тохирох бүтцлэгдсэн мэдээлэл гаргадаг. ӨНӨӨДРИЙН ОГНОО: {today_str}. 'Маргааш' гэсэн үг {tomorrow_str} гэсэн үг юм."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )
        
        ai_response = response.choices[0].message.content.strip()
        logger.info(f"AI response: {ai_response}")
        
        # JSON парсах оролдлого
        try:
            # JSON кодын хэсгийг олох
            import re
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                parsed_data = json.loads(json_str)
                
                # Default утгууд шалгах
                today = datetime.now()
                if not parsed_data.get('start_date'):
                    parsed_data['start_date'] = today.strftime("%Y-%m-%d")
                if not parsed_data.get('reason'):
                    parsed_data['reason'] = "day_off"
                if not parsed_data.get('status'):
                    parsed_data['status'] = "pending"
                if not parsed_data.get('inactive_hours'):
                    # Default 1 хоног = 8 цаг
                    parsed_data['inactive_hours'] = 8
                
                # Хуучин системтэй нийцүүлэх
                parsed_data['requester_name'] = user_name
                parsed_data['original_message'] = text
                
                # Хоногийн тоо зөв тооцоолох
                inactive_hours = parsed_data.get('inactive_hours', 8)
                if inactive_hours < 8:
                    # Цагийн чөлөө - 1 өдөр
                    parsed_data['days'] = 1
                else:
                    # Хоногийн чөлөө - цагаар хуваах
                    parsed_data['days'] = max(1, inactive_hours // 8)
                
                # End date тооцоолох
                if not parsed_data.get('end_date'):
                    start_date = datetime.strptime(parsed_data['start_date'], "%Y-%m-%d")
                    
                    if inactive_hours < 8:
                        # Цагийн чөлөө - тэр өдөр л
                        end_date = start_date
                    else:
                        # Хоногийн чөлөө - хоногийн тоогоор тооцоолох
                        end_date = start_date + timedelta(days=parsed_data['days'] - 1)
                    
                    parsed_data['end_date'] = end_date.strftime("%Y-%m-%d")
                
                return parsed_data
            else:
                logger.error("No JSON found in AI response")
                return parse_leave_request_simple(text, user_name)
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI JSON response: {e}")
            return parse_leave_request_simple(text, user_name)
            
    except Exception as e:
        logger.error(f"AI parsing error: {str(e)}")
        return parse_leave_request_simple(text, user_name)

def parse_leave_request_simple(text, user_name):
    """GPT model ашиглах fallback функц - keyword-based parsing багасгасан"""
    
    # Өнөөдрийн огноо олох
    today = datetime.now()
    
    # GPT model ашиглаж natural language ойлгох оролдлого
    try:
        if openai_client.api_key:
            # GPT-тэй холбогдох боломжтой бол түүнийг ашиглах
            return parse_leave_request(text, user_name)
    except Exception as e:
        logger.warning(f"GPT model ашиглах боломжгүй, энгийн parsing ашиглана: {str(e)}")
    
    # Fallback - зөвхөн хамгийн энгийн regex ашиглах
    text_lower = text.lower()
    
    # Мэдээлэл дутуу эсэхийг шалгах
    needs_clarification = True  # GPT ашиглахгүй бол үргэлж clarification шаардлагатай
    questions = ["GPT model ашиглах боломжгүй байна. Дэлгэрэнгүй мэдээлэл өгнө үү."]
    
    # Зөвхөн хамгийн энгийн тохиолдлуудыг шалгах
    today = datetime.now()
    
    # Default утгууд
    days = 1
    inactive_hours = 8
    start_date_obj = today
    reason = "day_off"
    
    # Зөвхөн хамгийн тодорхой тохиолдлуудыг шалгах
    if 'маргааш' in text_lower:
        start_date_obj = today + timedelta(days=1)
    
    start_date = start_date_obj.strftime("%Y-%m-%d")
    
    # End date тооцоолох
    if inactive_hours < 8:
        end_date_obj = start_date_obj
    else:
        end_date_obj = start_date_obj + timedelta(days=days-1)
    
    end_date = end_date_obj.strftime("%Y-%m-%d")
    
    return {
        "requester_name": user_name,
        "start_date": start_date,
        "end_date": end_date, 
        "days": days,
        "reason": reason,
        "inactive_hours": inactive_hours,
        "status": "pending",
        "needs_clarification": needs_clarification,
        "questions": questions,
        "original_message": text
    }

async def handle_leave_request_message(context: TurnContext, text, user_id, user_name):
    """Чөлөөний хүсэлтийн мессежийг боловсруулах"""
    try:
        # Хүсэлт гаргагчийн мэдээлэл олох
        requester_info = None
        for user in list_all_users():
            if user["user_id"] == user_id:
                requester_info = user
                break
        
        if not requester_info:
            await context.send_activity("❌ Таны мэдээлэл олдсонгүй. Эхлээд bot-тай чатлана уу.")
            return
        
        # Мессежээс мэдээлэл гаргах
        parsed_data = parse_leave_request(text, user_name or requester_info.get("user_name", "Unknown"))
        
        # Хүсэлтийн ID үүсгэх
        request_id = str(uuid.uuid4())
        
        # Хүсэлтийн мэдээлэл бэлтгэх
        # Dynamic manager ID авах - чөлөөний хугацаанаас хамааран тохирох manager-ийг олох
        requester_email = requester_info.get("email")
        leave_days = parsed_data.get("days", 1)  # Чөлөөний хоногийн тоо
        manager_id = get_available_manager_id(requester_email, leave_days)

        # Manager-ийн мэдээллийг авах (GUID биш бол э-мэйлээр fallback)
        manager_info = None
        if manager_id:
            try:
                access_token = get_graph_access_token()
                if access_token:
                    users_api = MicrosoftUsersAPI(access_token)
                    # Эхлээд GUID гэж үзэж оролдоно
                    manager_info = users_api.get_user_by_id(manager_id)
                    if not manager_info:
                        # GUID биш байж магадгүй тул э-мэйлээр (leader модулиас) fallback
                        try:
                            leader_info = get_user_manager_info(requester_email)
                            manager_email = leader_info.get('mail') if leader_info else None
                            if manager_email:
                                manager_info = users_api.get_user_by_email(manager_email)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Error getting manager info by ID/email {manager_id}: {str(e)}")
        
        request_data = {
            "request_id": request_id,
            "requester_email": requester_email,
            "requester_name": parsed_data["requester_name"],
            "requester_user_id": user_id,
            "start_date": parsed_data["start_date"],
            "end_date": parsed_data["end_date"],
            "days": parsed_data["days"],
            "reason": parsed_data["reason"],
            "inactive_hours": parsed_data.get("inactive_hours", parsed_data["days"] * 8),
            "status": parsed_data.get("status", "pending"),
            "original_message": text,
            "created_at": datetime.now().isoformat(),
            "approver_email": manager_info.get("mail") if manager_info else None,
            "approver_user_id": manager_id
        }
        
        # Хүсэлт хадгалах
        save_leave_request(request_data)
        
        # Хүсэлт гаргагчид хариулах
        await context.send_activity(f"✅ Чөлөөний хүсэлт хүлээн авлаа!\n📅 {parsed_data['start_date']} - {parsed_data['end_date']} ({parsed_data['days']} хоног)\n💭 {parsed_data['reason']}\n⏳ Зөвшөөрөлийн хүлээлгэд байна...{api_status_msg}")
        
        # Manager руу adaptive card илгээх
        approval_card = create_approval_card(request_data)
        approver_conversation = load_conversation_reference(manager_id) if manager_id else None
        
        # External API руу absence request үүсгэх
        api_result = await call_external_absence_api(request_data)
        api_status_msg = ""
        if api_result["success"]:
            api_status_msg = "\n✅ Системд амжилттай бүртгэгдлээ"
            # Absence ID хадгалах
            if api_result.get("absence_id"):
                request_data["absence_id"] = api_result["absence_id"]
                save_leave_request(request_data)  # Absence ID-тай дахин хадгалах
        else:
            api_status_msg = f"\n⚠️ Системд бүртгэхэд алдаа: {api_result.get('message', 'Unknown error')}"
        
        if approver_conversation:
            async def send_approval_card(ctx: TurnContext):
                adaptive_card_attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=approval_card
                )
                # Planner tasks мэдээлэл авах
                planner_info = ""
                if request_data.get("requester_email"):
                    try:
                        planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                    except Exception as e:
                        logger.error(f"Failed to get planner tasks for manager notification: {str(e)}")
                
                message = MessageFactory.attachment(adaptive_card_attachment)
                message.text = f"📩 Шинэ чөлөөний хүсэлт: {request_data['requester_name']}\n💬 Анхны мессеж: \"{text}\"{api_status_msg}{planner_info}"
                await ctx.send_activity(message)
            
            await ADAPTER.continue_conversation(
                approver_conversation,
                send_approval_card,
                app_id
            )
            logger.info(f"Leave request {request_id} sent to approver")
        else:
            logger.warning(f"Approver conversation reference not found for leave request {request_id}")
            # Approver-тай холбогдож чадахгүй байгаа тул хүсэлт хадгалагдсан гэдгийг мэдэгдэх
            await context.send_activity("⚠️ Зөвшөөрөгч bot-тай хараахан холбогдоогүй байна. Хүсэлт хадгалагдсан боловч зөвшөөрөгчтэй шууд холбогдоно уу.")
        
        logger.info(f"Leave request {request_id} created from message by {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling leave request message: {str(e)}")
        await context.send_activity(f"❌ Чөлөөний хүсэлт боловсруулахад алдаа гарлаа: {str(e)}")

async def forward_message_to_admin(text, user_name, user_id):
    """Ердийн мессежийг админд adaptive card-тай дамжуулах"""
    try:
        # Хэрэглэгчийн мэдээлэл олох
        requester_info = None
        all_users = list_all_users()
        
        for user in all_users:
            if user["user_id"] == user_id:
                requester_info = user
                break
        
        # Dynamic manager ID авах - чөлөөний хугацаанаас хамааран тохирох manager-ийг олох
        requester_email = requester_info.get("email") if requester_info else None
        if requester_email:
            # Энэ функц нь ердийн мессеж тул чөлөөний хоногийн тоог тодорхойлохгүй
            # Default 1 хоног гэж үзэж manager руу илгээнэ
            manager_id = get_available_manager_id(requester_email, 1)
            logger.info(f"Using available manager ID for {requester_email}: {manager_id}")
        else:
            manager_id = None
            logger.warning("No requester email found, cannot get manager ID")
        
        approver_conversation = load_conversation_reference(manager_id) if manager_id else None
        
        if approver_conversation:
            # Энгийн мессежээс чөлөөний хүсэлт үүсгэх
            parsed_data = parse_leave_request(text, user_name)
            
            # Хэрэв AI нь нэмэлт мэдээлэл хэрэгтэй гэж үзвэл
            if parsed_data.get('needs_clarification', False):
                questions = parsed_data.get('questions', [])
                if questions:
                    # Хэрэглэгчээс нэмэлт мэдээлэл асуух
                    question_text = "🤔 Чөлөөний хүсэлтийг боловсруулахын тулд нэмэлт мэдээлэл хэрэгтэй байна:\n\n"
                    for i, question in enumerate(questions, 1):
                        question_text += f"{i}. {question}\n"
                    question_text += "\nДахин мессеж илгээж дэлгэрэнгүй мэдээлэл өгнө үү."
                    
                    # Хэрэглэгчээс асуулт асуух логик нэмэх хэрэгтэй
                    # Одоогоор зөвхөн админд мэдэгдэх
                    async def notify_admin_clarification(ctx: TurnContext):
                        await ctx.send_activity(f"❓ {user_name} нэмэлт мэдээлэл хэрэгтэй:\n💬 Анхны мессеж: \"{text}\"\n🤔 Асуултууд: {', '.join(questions)}")
                    
                    await ADAPTER.continue_conversation(
                        approver_conversation,
                        notify_admin_clarification,
                        app_id
                    )
                    logger.info(f"Clarification needed message sent to admin from {user_id}")
                    return
            
            request_id = str(uuid.uuid4())
            
            # Хүсэлт гаргагчийн мэдээлэл олох
            requester_info = None
            all_users = list_all_users()
            
            for user in all_users:
                if user["user_id"] == user_id:
                    requester_info = user
                    break
            
            # Хүсэлтийн мэдээлэл бэлтгэх
            request_data = {
                "request_id": request_id,
                "requester_email": requester_info.get("email") if requester_info else "unknown@fibo.cloud",
                "requester_name": user_name,
                "requester_user_id": user_id,
                "start_date": parsed_data["start_date"],
                "end_date": parsed_data.get("end_date"),
                "days": parsed_data["days"],
                "reason": parsed_data["reason"],
                "inactive_hours": parsed_data.get("inactive_hours", parsed_data["days"] * 8),
                "status": parsed_data.get("status", "pending"),
                "original_message": text,
                "created_at": datetime.now().isoformat(),
                "approver_email": None,
                "approver_user_id": manager_id
            }
            
            # Хүсэлт хадгалах
            save_leave_request(request_data)
            
            # External API руу absence request үүсгэх
            api_result = await call_external_absence_api(request_data)
            api_status_msg = ""
            if api_result["success"]:
                api_status_msg = "\n✅ Системд амжилттай бүртгэгдлээ"
                # Absence ID хадгалах
                if api_result.get("absence_id"):
                    request_data["absence_id"] = api_result["absence_id"]
                    save_leave_request(request_data)  # Absence ID-тай дахин хадгалах
            else:
                api_status_msg = f"\n⚠️ Системд бүртгэхэд алдаа: {api_result.get('message', 'Unknown error')}"
            
            # Adaptive card үүсгэх
            approval_card = create_approval_card(request_data)
            
            async def notify_admin_with_card(ctx: TurnContext):
                adaptive_card_attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=approval_card
                )
                # Planner tasks мэдээлэл авах
                planner_info = ""
                if request_data.get("requester_email"):
                    try:
                        planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                    except Exception as e:
                        logger.error(f"Failed to get planner tasks for admin notification: {str(e)}")
                
                message = MessageFactory.attachment(adaptive_card_attachment)
                message.text = f"📨 Шинэ мессеж: {user_name}\n💬 Анхны мессеж: \"{text}\"\n🤖 AI ойлголт: {parsed_data.get('days')} хоног, {parsed_data.get('reason')}{api_status_msg}{planner_info}"
                await ctx.send_activity(message)
            
            await ADAPTER.continue_conversation(
                approver_conversation,
                notify_admin_with_card,
                app_id
            )
            logger.info(f"Message with adaptive card forwarded to admin from {user_id}")
        else:
            logger.warning(f"Approver conversation reference not found. Approver needs to message the bot first.")
            # Approver conversation байхгүй тул мессежийг log-д хадгална
            logger.info(f"Pending message for admin: {user_name} said: {text}")
    except Exception as e:
        logger.error(f"Error forwarding message to admin: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

def save_conversation_reference(activity):
    """Хэрэглэгчийн conversation reference болон нэмэлт мэдээллийг хадгалах функц"""
    try:
        reference = TurnContext.get_conversation_reference(activity)
        user_id = activity.from_property.id if activity.from_property else "unknown"
        conversation_id = activity.conversation.id if activity.conversation else "unknown"
        
        # Хэрэглэгчийн нэмэлт мэдээлэл цуглуулах
        user_info = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "user_name": getattr(activity.from_property, 'name', None) if activity.from_property else None,
            "email": None,
            "last_activity": activity.timestamp.isoformat() if activity.timestamp else None,
            "channel_id": activity.channel_id,
            "service_url": activity.service_url,
            "conversation_reference": reference.serialize(),
            "conversation_details": {
                "conversation_id": activity.conversation.id if activity.conversation else None,
                "conversation_type": getattr(activity.conversation, 'conversation_type', None) if activity.conversation else None,
                "tenant_id": getattr(activity.conversation, 'tenant_id', None) if activity.conversation else None,
                "is_group": getattr(activity.conversation, 'is_group', None) if activity.conversation else None,
                "name": getattr(activity.conversation, 'name', None) if activity.conversation else None
            }
        }
        
        # Мэйл хаяг олох оролдлого (Teams-ээс ихэвчлэн name дотор байдаг)
        if activity.from_property and activity.from_property.name:
            name = activity.from_property.name
            # Мэйл хаяг шиг харагдах эсэхийг шалгах
            if "@" in name and "." in name:
                user_info["email"] = name
                # User name-г мэйлээс салгаж авах
                if " <" in name:
                    user_info["user_name"] = name.split(" <")[0]
                    user_info["email"] = name.split(" <")[1].rstrip(">")
                elif "<" in name and ">" in name:
                    user_info["email"] = name.split("<")[1].split(">")[0]
            else:
                # Мэйл хаяг байхгүй бол display name-аас үүсгэх
                # "Tuvshinjargal Enkhtaivan" -> "tuvshinjargal@fibo.cloud"
                user_info["user_name"] = name
                if name and name.strip():
                    # Эхний үгийг авч жижиг үсэг болгох
                    first_name = name.strip().split()[0].lower()
                    # Тусгай тэмдэгтүүдийг арилгах
                    first_name = re.sub(r'[^a-zA-Z0-9]', '', first_name)
                    user_info["email"] = f"{first_name}@fibo.cloud"
        
        # Additional Azure AD properties шалгах
        if hasattr(activity.from_property, 'aad_object_id'):
            user_info["aad_object_id"] = activity.from_property.aad_object_id
        
        # Хэрэглэгчийн ID-ээр файлын нэр үүсгэх (special characters-ээс зайлсхийх)
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(user_info, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved conversation reference for user {user_id} (email: {user_info.get('email', 'N/A')}) to {filename}")
        return filename
    except Exception as e:
        logger.error(f"Failed to save conversation reference: {str(e)}")
        return None

def load_conversation_reference(user_id):
    """Хэрэглэгчийн conversation reference-г унших функц"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            logger.error(f"Conversation file not found for user {user_id}")
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            user_info = json.load(f)
        
        # Хуучин формат шалгах (зөвхөн conversation_reference байх)
        if "conversation_reference" in user_info:
            return ConversationReference().deserialize(user_info["conversation_reference"])
        else:
            # Хуучин формат байна гэж үзэж
            return ConversationReference().deserialize(user_info)
    except Exception as e:
        logger.error(f"Failed to load conversation reference for user {user_id}: {str(e)}")
        return None

def load_user_info(user_id):
    """Хэрэглэгчийн бүрэн мэдээллийг унших функц"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load user info for {user_id}: {str(e)}")
        return None

def list_all_users():
    """Хадгалагдсан бүх хэрэглэгчийн дэлгэрэнгүй мэдээлэл гаргах"""
    try:
        users = []
        for filename in os.listdir(CONVERSATION_DIR):
            if filename.startswith("user_") and filename.endswith(".json"):
                user_id = filename[5:-5].replace("_", ":")  # user_ prefix болон .json suffix арилгах
                user_info = load_user_info(user_id)
                if user_info:
                    # Хуучин формат шалгах
                    if "user_id" in user_info:
                        users.append({
                            "user_id": user_info.get("user_id", user_id),
                            "email": user_info.get("email"),
                            "user_name": user_info.get("user_name"),
                            "last_activity": user_info.get("last_activity"),
                            "channel_id": user_info.get("channel_id"),
                            "conversation_id": user_info.get("conversation_id"),
                            "conversation_type": user_info.get("conversation_details", {}).get("conversation_type"),
                            "tenant_id": user_info.get("conversation_details", {}).get("tenant_id"),
                            "is_group": user_info.get("conversation_details", {}).get("is_group"),
                            "conversation_name": user_info.get("conversation_details", {}).get("name")
                        })
                    else:
                        # Хуучин формат - зөвхөн user_id нэмэх
                        users.append({
                            "user_id": user_id,
                            "email": None,
                            "user_name": None,
                            "last_activity": None,
                            "channel_id": None,
                            "conversation_id": None,
                            "conversation_type": None,
                            "tenant_id": None,
                            "is_group": None,
                            "conversation_name": None
                        })
                else:
                    users.append({
                        "user_id": user_id,
                        "email": None,
                        "user_name": None,
                        "last_activity": None,
                        "channel_id": None,
                        "conversation_id": None,
                        "conversation_type": None,
                        "tenant_id": None,
                        "is_group": None,
                        "conversation_name": None
                    })
        return users
    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}")
        return []

def find_user_by_conversation_id(conversation_id):
    """Conversation ID-аар хэрэглэгч олох"""
    for user in list_all_users():
        if user.get("conversation_id") == conversation_id:
            return user
    return None

def save_user_absence_id(user_id, absence_id):
    """Хэрэглэгчийн файлд absence_id хадгалах"""
    try:
        user_info = load_user_info(user_id)
        if user_info:
            user_info["current_absence_id"] = absence_id
            user_info["absence_updated_at"] = datetime.now().isoformat()
            
            safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
            filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(user_info, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved absence_id {absence_id} for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to save absence_id for user {user_id}: {str(e)}")
        return False

def get_user_absence_id(user_id):
    """Хэрэглэгчийн absence_id авах"""
    try:
        user_info = load_user_info(user_id)
        if user_info:
            return user_info.get("current_absence_id")
    except Exception as e:
        logger.error(f"Failed to get absence_id for user {user_id}: {str(e)}")
    return None

def clear_user_absence_id(user_id):
    """Хэрэглэгчийн absence_id устгах"""
    try:
        user_info = load_user_info(user_id)
        if user_info:
            user_info.pop("current_absence_id", None)
            user_info.pop("absence_updated_at", None)
            
            safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
            filename = f"{CONVERSATION_DIR}/user_{safe_user_id}.json"
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(user_info, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Cleared absence_id for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to clear absence_id for user {user_id}: {str(e)}")
        return False

@app.route("/", methods=["GET"])
def health_check():
    pending_confirmations = len([f for f in os.listdir(PENDING_CONFIRMATIONS_DIR) if f.startswith("pending_") and not f.startswith("pending_rejection_")]) if os.path.exists(PENDING_CONFIRMATIONS_DIR) else 0
    pending_rejections = len([f for f in os.listdir(PENDING_CONFIRMATIONS_DIR) if f.startswith("pending_rejection_")]) if os.path.exists(PENDING_CONFIRMATIONS_DIR) else 0
    
    # HR Manager-уудын тоо шалгах - хасагдсан
    
    return jsonify({
        "status": "running",
        "message": "Flask Bot Server is running",
        "endpoints": ["/api/messages", "/proactive-message", "/users", "/broadcast", "/leave-request", "/approval-callback", "/send-by-conversation", "/manager-timeout-test", "/replacement-worker", "/replacement-workers/<email>", "/auto-remove-replacement-workers", "/cleanup-expired-leaves"],
        "app_id_configured": bool(os.getenv("MICROSOFT_APP_ID")),
        "stored_users": len(list_all_users()),
        "pending_confirmations": pending_confirmations,
        "pending_rejections": pending_rejections,
        "active_timers": len(active_timers),
        "confirmation_timeout_minutes": CONFIRMATION_TIMEOUT_SECONDS // 60,
        "manager_pending_actions": len(manager_pending_actions),
        "manager_response_timeout_hours": MANAGER_RESPONSE_TIMEOUT_SECONDS // 3600,
        "microsoft_graph_configured": bool(TENANT_ID and CLIENT_ID and CLIENT_SECRET)
    })

@app.route("/users", methods=["GET"])
def get_users():
    """Хадгалагдсан хэрэглэгчдийн жагсаалт"""
    users = list_all_users()
    return jsonify({"users": users, "count": len(users)})

# HR Manager endpoint хасагдсан

@app.route("/manager-timeout-test", methods=["POST"])
def test_manager_timeout():
    """Manager timeout механизмыг тест хийх (debug зорилгоор)"""
    try:
        data = request.get_json()
        request_id = data.get("request_id")
        
        if not request_id:
            return jsonify({
                "status": "error",
                "message": "request_id шаардлагатай"
            }), 400
        
        # Test request data үүсгэх
        test_request_data = {
            "request_id": request_id,
            "requester_name": "Test User",
            "requester_email": "test@fibo.cloud",
            "start_date": "2024-01-15",
            "end_date": "2024-01-16",
            "days": 1,
            "reason": "Test timeout",
            "original_message": "Тест зорилгоор timeout механизм шалгах",
            "created_at": datetime.now().isoformat()
        }
        
        # Manager timeout тест (5 секунд)
        test_timer = threading.Timer(5, handle_manager_response_timeout, args=[request_id, test_request_data])
        test_timer.start()
        manager_pending_actions[request_id] = test_timer
        
        logger.info(f"Test manager timeout timer эхлэсэн: {request_id}")
        
        return jsonify({
            "status": "success", 
            "message": f"Test timer эхлэсэн. 5 секундын дараа HR-руу мэдэгдэл илгээгдэнэ.",
            "request_id": request_id,
            "test_timeout_seconds": 5
        })
        
    except Exception as e:
        logger.error(f"Manager timeout test алдаа: {str(e)}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route("/replacement-worker", methods=["POST"])
def assign_replacement_worker_endpoint():
    """Орлон ажиллах хүн томилох API"""
    try:
        data = request.get_json()
        requester_email = data.get("requester_email", "").strip()
        replacement_email = data.get("replacement_email", "").strip()
        
        if not requester_email or not replacement_email:
            return jsonify({
                "success": False,
                "message": "requester_email болон replacement_email шаардлагатай"
            }), 400
        
        result = assign_replacement_worker(requester_email, replacement_email)
        
        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Replacement worker assign endpoint алдаа: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route("/replacement-worker", methods=["DELETE"])
def remove_replacement_worker_endpoint():
    """Орлон ажиллах хүн хасах API"""
    try:
        data = request.get_json()
        requester_email = data.get("requester_email", "").strip()
        replacement_email = data.get("replacement_email", "").strip()
        
        if not requester_email or not replacement_email:
            return jsonify({
                "success": False,
                "message": "requester_email болон replacement_email шаардлагатай"
            }), 400
        
        result = remove_replacement_worker(requester_email, replacement_email)
        
        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Replacement worker remove endpoint алдаа: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route("/replacement-workers/<email>", methods=["GET"])
def get_replacement_workers_endpoint(email):
    """Орлон ажиллах хүмүүсийг жагсаах API"""
    try:
        result = get_replacement_workers(email)
        
        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Get replacement workers endpoint алдаа: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route("/auto-remove-replacement-workers", methods=["POST"])
def auto_remove_replacement_workers_endpoint():
    """Чөлөө дуусахад орлон ажиллах хүмүүсийг автоматаар хасах API"""
    try:
        data = request.get_json()
        requester_email = data.get("requester_email", "").strip()
        
        if not requester_email:
            return jsonify({
                "success": False,
                "message": "requester_email шаардлагатай"
            }), 400
        
        result = auto_remove_replacement_workers_on_leave_end(requester_email)
        
        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Auto remove replacement workers endpoint алдаа: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route("/cleanup-expired-leaves", methods=["POST"])
def cleanup_expired_leaves_endpoint():
    """Дууссан чөлөөний орлон ажиллах хүмүүсийг цэвэрлэх API"""
    try:
        # Async функцийг sync context-д дуудах
        import asyncio
        result = asyncio.run(check_and_cleanup_expired_leaves())
        
        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Cleanup expired leaves endpoint алдаа: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route("/leave-request", methods=["POST"])
def submit_leave_request():
    """Чөлөөний хүсэлт гаргах"""
    try:
        data = request.json
        requester_email = data.get("requester_email")
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        days = data.get("days")
        reason = data.get("reason", "day_off")
        original_message = data.get("original_message", "")

        if not all([requester_email, start_date, end_date, days]):
            return jsonify({"error": "Missing required fields: requester_email, start_date, end_date, days"}), 400

        # Хүсэлт гаргагчийн мэдээлэл олох
        requester_info = None
        for user in list_all_users():
            if user["email"] == requester_email:
                requester_info = user
                break

        if not requester_info:
            return jsonify({"error": f"User with email {requester_email} not found"}), 404

        # Dynamic manager ID авах - чөлөөний хугацаанаас хамааран тохирох manager-ийг олох
        manager_id = get_available_manager_id(requester_email, days)
        
        # Manager-ийн мэдээллийг авах (GUID биш тохиолдолд э-мэйлээр fallback)
        manager_info = None
        if manager_id:
            try:
                access_token = get_graph_access_token()
                if access_token:
                    users_api = MicrosoftUsersAPI(access_token)
                    manager_info = users_api.get_user_by_id(manager_id)
                    if not manager_info:
                        try:
                            leader_info = get_user_manager_info(requester_email)
                            manager_email = leader_info.get('mail') if leader_info else None
                            if manager_email:
                                manager_info = users_api.get_user_by_email(manager_email)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Error getting manager info by ID/email {manager_id}: {str(e)}")
        else:
            manager_info = None
        
        # Хүсэлтийн мэдээлэл бэлтгэх
        request_id = str(uuid.uuid4())
        request_data = {
            "request_id": request_id,
            "requester_email": requester_email,
            "requester_name": requester_info.get("user_name", requester_email),
            "requester_user_id": requester_info["user_id"],
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "reason": reason,
            "inactive_hours": days * 8,  # 8 цагийн ажлын өдөр
            "status": "pending",
            "original_message": original_message,
            "created_at": datetime.now().isoformat(),
            "approver_email": manager_info.get("mail") if manager_info else None,
            "approver_user_id": manager_id
        }

        # Хүсэлт хадгалах
        if not save_leave_request(request_data):
            return jsonify({"error": "Failed to save leave request"}), 500

        # External API руу absence request үүсгэх
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        api_result = loop.run_until_complete(call_external_absence_api(request_data))
        
        api_status_msg = ""
        if api_result["success"]:
            api_status_msg = "\n✅ Системд амжилттай бүртгэгдлээ"
            # Absence ID хадгалах
            if api_result.get("absence_id"):
                request_data["absence_id"] = api_result["absence_id"]
                save_leave_request(request_data)  # Absence ID-тай дахин хадгалах
        else:
            api_status_msg = f"\n⚠️ Системд бүртгэхэд алдаа: {api_result.get('message', 'Unknown error')}"

        # Approval card үүсгэх
        approval_card = create_approval_card(request_data)

        # Approver руу adaptive card илгээх
        approver_conversation = load_conversation_reference(manager_id) if manager_id else None
        if not approver_conversation:
            return jsonify({"error": f"Manager conversation reference not found for {manager_id}"}), 404

        async def send_approval_card(context: TurnContext):
            adaptive_card_attachment = Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=approval_card
            )
            # Planner tasks мэдээлэл авах
            planner_info = ""
            if request_data.get("requester_email"):
                try:
                    planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                except Exception as e:
                    logger.error(f"Failed to get planner tasks for REST API request: {str(e)}")
            
            message = MessageFactory.attachment(adaptive_card_attachment)
            message.text = f"📩 Шинэ чөлөөний хүсэлт: {request_data['requester_name']}\n💬 REST API-аас илгээгдсэн{api_status_msg}{planner_info}"
            await context.send_activity(message)

        asyncio.run(
            ADAPTER.continue_conversation(
                approver_conversation,
                send_approval_card,
                app_id
            )
        )

        # Хүсэлт гаргагч руу баталгаажуулах мессеж илгээх
        requester_conversation = load_conversation_reference(requester_info["user_id"])
        if requester_conversation:
            async def send_confirmation(context: TurnContext):
                await context.send_activity(f"✅ Таны чөлөөний хүсэлт амжилттай илгээгдлээ!\n📅 {start_date} - {end_date} ({days} хоног)\n⏳ Зөвшөөрөлийн хүлээлгэд байна...")

            asyncio.run(
                ADAPTER.continue_conversation(
                    requester_conversation,
                    send_confirmation,
                    app_id
                )
            )

        logger.info(f"Leave request {request_id} submitted by {requester_email}")
        return jsonify({
            "status": "success",
            "request_id": request_id,
            "message": "Leave request submitted successfully"
        }), 200

    except Exception as e:
        logger.error(f"Leave request error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages", methods=["POST"])
def process_messages():
    try:
        logger.info("Received message request")
        if not request.is_json:
            logger.error("Request is not JSON")
            return jsonify({"error": "Content-Type must be application/json"}), 400

        body = request.get_json()
        logger.info(f"Request body: {body}")

        if not body:
            logger.error("Empty request body")
            return jsonify({"error": "Request body is required"}), 400

        try:
            activity = Activity().deserialize(body)
            logger.info(f"Activity type: {activity.type}, text: {activity.text}")
        except Exception as e:
            logger.error(f"Failed to deserialize activity: {str(e)}")
            return jsonify({"error": f"Invalid activity format: {str(e)}"}), 400

        # Хэрэглэгчийн conversation reference хадгалах
        save_conversation_reference(activity)

        async def logic(context: TurnContext):
            try:
                if activity.type == "message":
                    # Adaptive card action шалгах
                    if activity.value:
                        # Adaptive card submit/execute action ялгах
                        action_data = activity.value
                        try:
                            # Менежерийн approval картууд нь data-д action + request_id дамжуулдаг
                            if isinstance(action_data, dict) and action_data.get("action") in {"approve", "reject"} and action_data.get("request_id"):
                                await handle_adaptive_card_action(context, action_data)
                            else:
                                # Хэрэглэгчийн wizard урсгалын картын үйлдлүүд
                                await handle_user_adaptive_card_action(context, action_data)
                        except Exception as e:
                            logger.error(f"Error dispatching adaptive card action: {str(e)}")
                            await context.send_activity("❌ Картын үйлдлийг боловсруулахад алдаа гарлаа.")
                    else:
                        # Ердийн мессеж
                        user_text = activity.text or "No text provided"
                        user_id = activity.from_property.id if activity.from_property else "unknown"
                        user_name = getattr(activity.from_property, 'name', None) if activity.from_property else "Unknown User"
                        logger.info(f"Processing message from user {user_id}: {user_text}")
                        
                        # Зөвхөн manager биш хэрэглэгчдийн мессежийг боловсруулах
                        # Dynamic manager ID-г шалгах
                        is_manager = False
                        try:
                            # Хэрэглэгчийн мэдээлэл олох
                            requester_info = None
                            all_users = list_all_users()
                            
                            for user in all_users:
                                if user["user_id"] == user_id:
                                    requester_info = user
                                    break
                            
                            if requester_info and requester_info.get("email"):
                                # Энэ хэрэглэгчийн manager-ийг олох - чөлөөний хугацаанаас хамааран тохирох manager-ийг олох
                                # Default 1 хоног гэж үзэж manager шалгах
                                manager_id = get_available_manager_id(requester_info["email"], 1)
                                if manager_id == user_id:
                                    is_manager = True
                        except Exception as e:
                            logger.warning(f"Error checking if user is manager: {str(e)}")
                            # Алдаа гарвал manager биш гэж үзэх
                            is_manager = False
                        
                        if not is_manager:
                            # Чөлөөний түлхүүр үг илэрвэл wizard-ийг эхлүүлэх
                            try:
                                if is_leave_request(user_text):
                                    # Wizard эхлүүлэх - төрөл сонгох карт илгээх
                                    leave_type_card = create_leave_type_card()
                                    adaptive_card_attachment = Attachment(
                                        content_type="application/vnd.microsoft.card.adaptive",
                                        content=leave_type_card
                                    )
                                    await context.send_activity(MessageFactory.attachment(adaptive_card_attachment))
                                    # Wizard-ийн түр өгөгдөл хадгалах
                                    wizard_request_id = str(uuid.uuid4())
                                    wizard_data = {
                                        "request_id": wizard_request_id,
                                        "status": "wizard",
                                        "wizard": {
                                            "step": "choose_type"
                                        },
                                        "requester_user_id": user_id,
                                        "requester_name": user_name,
                                    }
                                    save_pending_confirmation(user_id, wizard_data)
                                    return
                            except Exception as e:
                                logger.warning(f"Failed to start wizard: {str(e)}")
                                # Алдаа гарвал хуучин урсгалаар үргэлжлүүлнэ
                            # Хэрэв хэрэглэгчтэй pending confirmation байвал
                            pending_confirmation = load_pending_confirmation(user_id)
                            
                            if pending_confirmation:
                                # Wizard: шалтгаан мессежээр хүлээж авах үе
                                try:
                                    pd = pending_confirmation.get("request_data", {}) if isinstance(pending_confirmation, dict) else {}
                                    wizard_state = pd.get("wizard", {})
                                    if pd.get("status") == "wizard" and wizard_state.get("step") == "await_reason":
                                        reason_text = user_text.strip()
                                        # Reason хадгалах
                                        wizard_state["reason"] = reason_text
                                        wizard_state["step"] = "date_time"
                                        pd["wizard"] = wizard_state
                                        save_pending_confirmation(user_id, pd)
                                        # GPT-ээр парслах
                                        parsed = parse_leave_request(reason_text, user_name)
                                        wizard_state["parsed"] = parsed
                                        pd["wizard"] = wizard_state
                                        save_pending_confirmation(user_id, pd)
                                        # Дараагийн карт: хугацаа/цаг
                                        date_time_card = create_date_time_card(parsed, leave_type=wizard_state.get("leave_type"), reason_text=reason_text)
                                        attachment = Attachment(content_type="application/vnd.microsoft.card.adaptive", content=date_time_card)
                                        await context.send_activity(MessageFactory.attachment(attachment))
                                        return
                                except Exception as e:
                                    logger.warning(f"Failed to process await_reason message: {str(e)}")
                                # Хэрэв wizard урсгал идэвхтэй байвал, товч дарж үргэлжлүүлэхийг сануулах
                                try:
                                    pd = pending_confirmation.get("request_data", {}) if isinstance(pending_confirmation, dict) else {}
                                    if (pd.get("status") == "wizard") or (pending_confirmation.get("status") == "wizard"):
                                        await context.send_activity("🧭 Чөлөөний хүсэлтийн алхамт урсгал идэвхтэй байна. Картан дээрх товчийг ашиглан үргэлжлүүлнэ үү.")
                                        return
                                except Exception:
                                    pass
                                # Баталгаажуулалтын хариу шалгах
                                confirmation_response = is_confirmation_response(user_text)
                                
                                if confirmation_response == "approve":
                                    # Зөвшөөрсөн - менежер руу илгээх
                                    request_data = pending_confirmation["request_data"]
                                    
                                    # Timer цуцлах ба баталгаажуулалт устгах
                                    delete_pending_confirmation(user_id)
                                    
                                    # Хүсэлт хадгалах
                                    save_leave_request(request_data)
                                    
                                    # External API руу absence request үүсгэх
                                    api_result = await call_external_absence_api(request_data)
                                    api_status_msg = ""
                                    if api_result["success"]:
                                        api_status_msg = "\n✅ Системд амжилттай бүртгэгдлээ"
                                        # Absence ID хадгалах
                                        if api_result.get("absence_id"):
                                            request_data["absence_id"] = api_result["absence_id"]
                                            save_leave_request(request_data)  # Absence ID-тай дахин хадгалах
                                            
                                            # Хэрэглэгчийн файлд absence_id хадгалах
                                            save_user_absence_id(user_id, api_result["absence_id"])
                                    else:
                                        api_status_msg = f"\n⚠️ Системд бүртгэхэд алдаа: {api_result.get('message', 'Unknown error')}"
                                    
                                    # await context.send_activity(f"✅ Чөлөөний хүсэлт баталгаажсан!\n📤 Менежер руу илгээгдэж байна...{api_status_msg}")
                                    await context.send_activity(f"Ахлах руу илгээгдэж байна...")
                                    
                                    # Менежер руу илгээх
                                    await send_approved_request_to_manager(request_data, user_text)
                                    
                                elif confirmation_response == "reject":
                                    # Татгалзсан - timer цуцлах ба дахин оруулахыг хүсэх
                                    delete_pending_confirmation(user_id)
                                    await context.send_activity("❌ Баталгаажуулалт цуцлагдлаа.\n\n🔄 Чөлөөний хүсэлтээ дахин илгээнэ үү. Дэлгэрэнгүй мэдээлэлтэй бичнэ үү.")
                                    
                                elif confirmation_response == "cancel":
                                    # Цуцалсан - timer цуцлах ба manager-д мэдэгдэх
                                    request_data = pending_confirmation["request_data"]
                                    delete_pending_confirmation(user_id)
                                    
                                    # External API дээр absence цуцлах
                                    cancellation_api_result = None
                                    absence_id = request_data.get("absence_id") or get_user_absence_id(user_id)
                                    
                                    if absence_id:
                                        cancellation_api_result = await call_reject_absence_api(
                                            absence_id, 
                                            "Хэрэглэгч өөрөө цуцалсан"
                                        )
                                        if cancellation_api_result["success"]:
                                            logger.info(f"External API cancellation successful for absence_id: {absence_id}")
                                            # Хэрэглэгчийн absence_id устгах (цуцалсан тул)
                                            clear_user_absence_id(user_id)
                                        else:
                                            logger.error(f"External API cancellation failed: {cancellation_api_result.get('message', 'Unknown error')}")
                                    else:
                                        logger.warning(f"No absence_id found for cancellation - request {request_data.get('request_id')} or user {user_id}")
                                    
                                    # API статус мэдээлэл
                                    api_status_msg = ""
                                    if cancellation_api_result:
                                        if cancellation_api_result["success"]:
                                            api_status_msg = "\n✅ Системээс мөн цуцлагдлаа"
                                        else:
                                            api_status_msg = f"\n⚠️ Системээс цуцлахад алдаа: {cancellation_api_result.get('message', 'Unknown error')}"
                                    
                                    await context.send_activity(f"🚫 Чөлөөний хүсэлт цуцлагдлаа.{api_status_msg}\n\n💼 Ахлагч танд мэдэгдэж байна.")
                                    
                                    # Manager руу цуцлах мэдээлэл илгээх
                                    await send_cancellation_to_manager(request_data, user_text, cancellation_api_result)
                                    
                                else:
                                    # Ойлгомжгүй хариу
                                    await context.send_activity('🤔 Ойлгосонгүй. "Тийм", "Үгүй" эсвэл "Цуцлах" гэж хариулна уу.\n\n• **"Тийм"** - Менежер руу илгээх\n• **"Үгүй"** - Засварлах\n• **"Цуцлах"** - Бүрэн цуцлах')
                                
                                return
                            
                            # Шинэ хүсэлт - AI ашиглаж parse хийх
                            parsed_data = parse_leave_request(user_text, user_name)
                            
                            # Хэрэв AI нь нэмэлт мэдээлэл хэрэгтэй гэж үзвэл
                            if parsed_data.get('needs_clarification', False):
                                questions = parsed_data.get('questions', [])
                                if questions:
                                    # Хэрэглэгчээс нэмэлт мэдээлэл асуух
                                    question_text = "🤔 Чөлөөний хүсэлтийг боловсруулахын тулд нэмэлт мэдээлэл хэрэгтэй байна:\n\n"
                                    for i, question in enumerate(questions, 1):
                                        question_text += f"{i}. {question}\n"
                                    question_text += "\nДахин мессеж илгээж дэлгэрэнгүй мэдээлэл өгнө үү."
                                    
                                    await context.send_activity(question_text)
                                    logger.info(f"Asked clarification questions to user {user_id}")
                                    return
                            
                            # Мэдээлэл хангалттай - баталгаажуулалт асуух
                            # Request data бэлтгэх
                            request_id = str(uuid.uuid4())
                            
                            # Хэрэглэгчийн мэдээлэл олох
                            requester_info = None
                            all_users = list_all_users()
                            for user in all_users:
                                if user["user_id"] == user_id:
                                    requester_info = user
                                    break
                            
                            # Dynamic manager ID авах - чөлөөний хугацаанаас хамааран тохирох manager-ийг олох
                            requester_email = requester_info.get("email") if requester_info else "unknown@fibo.cloud"
                            leave_days = parsed_data.get("days", 1)  # Чөлөөний хоногийн тоо
                            manager_id = get_available_manager_id(requester_email, leave_days)
                            
                            # Manager-ийн мэдээллийг авах (GUID биш бол э-мэйлээр fallback)
                            manager_info = None
                            if manager_id:
                                try:
                                    access_token = get_graph_access_token()
                                    if access_token:
                                        users_api = MicrosoftUsersAPI(access_token)
                                        # Эхлээд GUID гэж үзэж ID-аар оролдоно
                                        manager_info = users_api.get_user_by_id(manager_id)
                                        if not manager_info:
                                            # GUID биш байж магадгүй тул leader модулиас имэйл авч Graph-с имэйлээр татах
                                            try:
                                                leader_info = get_user_manager_info(requester_email)
                                                manager_email = leader_info.get('mail') if leader_info else None
                                                if manager_email:
                                                    manager_info = users_api.get_user_by_email(manager_email)
                                            except Exception:
                                                pass
                                except Exception as e:
                                    logger.error(f"Error getting manager info by ID/email {manager_id}: {str(e)}")
                                    manager_info = None
                            else:
                                manager_info = None
                            
                            request_data = {
                                "request_id": request_id,
                                "requester_email": requester_email,
                                "requester_name": user_name,
                                "requester_user_id": user_id,
                                "start_date": parsed_data["start_date"],
                                "end_date": parsed_data.get("end_date"),
                                "days": parsed_data["days"],
                                "reason": parsed_data["reason"],
                                "inactive_hours": parsed_data.get("inactive_hours", parsed_data["days"] * 8),
                                "status": parsed_data.get("status", "pending"),
                                "original_message": user_text,
                                "created_at": datetime.now().isoformat(),
                                "approver_email": manager_info.get("mail") if manager_info else None,
                                "approver_user_id": manager_id
                            }
                            
                            # Pending confirmation хадгалах
                            save_pending_confirmation(user_id, request_data)
                            
                            # Баталгаажуулалт асуух
                            confirmation_message = create_confirmation_message(parsed_data, requester_info.get("email"))
                            await context.send_activity(confirmation_message)
                            
                            logger.info(f"Asked for confirmation from user {user_id}")
                            
                        else:
                            # Manager өөрийн мессеж - pending rejection шалгах
                            pending_rejection = load_pending_rejection(user_id)
                            
                            if pending_rejection:
                                # Manager татгалзах шалтгаан илгээсэн
                                rejection_reason = user_text.strip()
                                request_data = pending_rejection["request_data"]
                                
                                # Pending rejection устгах
                                delete_pending_rejection(user_id)
                                
                                # Request data шинэчлэх
                                request_data["status"] = "rejected"
                                request_data["rejected_at"] = datetime.now().isoformat()
                                request_data["rejected_by"] = user_id
                                request_data["rejection_reason"] = rejection_reason
                                
                                # External API руу rejection дуудлага хийх
                                rejection_api_result = None
                                absence_id = request_data.get("absence_id") or get_user_absence_id(request_data["requester_user_id"])
                                
                                if absence_id:
                                    rejection_api_result = await call_reject_absence_api(
                                        absence_id, 
                                        rejection_reason
                                    )
                                    if rejection_api_result["success"]:
                                        logger.info(f"External API rejection successful for absence_id: {absence_id}")
                                    else:
                                        logger.error(f"External API rejection failed: {rejection_api_result.get('message', 'Unknown error')}")
                                else:
                                    logger.warning(f"No absence_id found for request {request_data['request_id']} or user {request_data['requester_user_id']}, skipping external rejection")
                                
                                # Хүсэлт хадгалах
                                save_leave_request(request_data)
                                
                                # Хэрэглэгчийн absence_id устгах (татгалзагдсан тул)
                                clear_user_absence_id(request_data["requester_user_id"])
                                
                                # Manager-д баталгаажуулах
                                api_status_msg = ""
                                if rejection_api_result:
                                    if rejection_api_result["success"]:
                                        api_status_msg = "\n✅ Системд автоматаар татгалзагдлаа"
                                    else:
                                        api_status_msg = f"\n⚠️ Системд татгалзахад алдаа: {rejection_api_result.get('message', 'Unknown error')}"
                                
                                await context.send_activity(f"✅ Чөлөөний хүсэлт татгалзагдлаа!\n📝 Хүсэлт: {request_data['requester_name']} - {request_data['start_date']} ({request_data['days']} хоног)\n💬 Татгалзах шалтгаан: \"{rejection_reason}\"\n📤 Хүсэлт гаргагчид мэдэгдэж байна...{api_status_msg}")
                                
                                # Хүсэлт гаргагч руу мэдэгдэх
                                requester_conversation = load_conversation_reference(request_data["requester_user_id"])
                                if requester_conversation:
                                    async def notify_rejection(ctx: TurnContext):
                                        await ctx.send_activity(f"❌ Таны чөлөөний хүсэлт татгалзагдлаа\n📅 {request_data['start_date']} - {request_data['end_date']} ({request_data['days']} хоног)\n💬 Татгалзах шалтгаан: \"{rejection_reason}\"\n\n🔄 Хэрэв шинэ хүсэлт гаргах бол дэлгэрэнгүй мэдээлэлтэй бичнэ үү.")

                                    await ADAPTER.continue_conversation(
                                        requester_conversation,
                                        notify_rejection,
                                        app_id
                                    )
                                
                                logger.info(f"Leave request {request_data['request_id']} rejected by {user_id} with reason: {rejection_reason}")
                            else:
                                # Ердийн мессеж - зөвхөн echo хариу
                                await context.send_activity(f"Таны мессежийг хүлээн авлаа: {user_text}")
                                logger.info(f"Skipping forwarding message to admin from approver himself: {user_id}")
                elif activity.type == "invoke":
                    # Action.Execute дэмжлэг (Teams Adaptive Card)
                    try:
                        name = getattr(activity, 'name', None)
                        if name == "adaptiveCard/action":
                            raw = activity.value or {}
                            action = raw.get("action", {}) if isinstance(raw, dict) else {}
                            inputs = raw.get("data", {}) if isinstance(raw, dict) else {}
                            # Нэгтгэж payload үүсгэх (verb + data + inputs)
                            payload = {**inputs}
                            if isinstance(action, dict):
                                if action.get("verb"):
                                    payload["verb"] = action.get("verb")
                                # Action.Submit-тэй нийцүүлэхийн тулд data-г нийлүүлэх
                                if isinstance(action.get("data"), dict):
                                    payload.update(action.get("data"))
                            # Менежер эсэхээс үл хамааран хэрэглэгчийн invoke handler-рүү өгөх
                            user_id = activity.from_property.id if activity.from_property else "unknown"
                            user_name = getattr(activity.from_property, 'name', None) if activity.from_property else "Unknown User"
                            card_to_return = await handle_user_adaptive_card_action_invoke(context, payload, user_id, user_name)
                            # Sequential update-ыг дэмжихгүй хувилбаруудад нийцтэй: дараагийн картын мессеж явуулах
                            if card_to_return:
                                attachment = Attachment(content_type="application/vnd.microsoft.card.adaptive", content=card_to_return)
                                await context.send_activity(MessageFactory.attachment(attachment))
                        else:
                            logger.info(f"Unhandled invoke name: {name}")
                    except Exception as e:
                        logger.error(f"Invoke handling error: {str(e)}")
                        await context.send_activity(f"❌ Картын үйлдлийг боловсруулахад алдаа гарлаа: {str(e)}")
                else:
                    logger.info(f"Non-message activity type: {activity.type}")
            except Exception as e:
                logger.error(f"Error in logic function: {str(e)}")
                await context.send_activity(f"Серверийн алдаа: {str(e)}")

        try:
            auth_header = request.headers.get('Authorization', '')
            logger.info(f"Auth header present: {bool(auth_header)}")
            asyncio.run(ADAPTER.process_activity(activity, auth_header, logic))
            logger.info("Message processed successfully")
            return jsonify({"status": "success"}), 200
        except Exception as e:
            logger.error(f"Adapter processing error: {str(e)}")
            return jsonify({"error": f"Bot framework error: {str(e)}"}), 500

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

def create_leave_type_card():
    """1-р шат: Чөлөөний төрөл сонгох Adaptive Card"""
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "1. Чөлөөний төрөл сонгоно уу", "wrap": True, "weight": "Bolder", "size": "Medium"},
            {
                "type": "Input.ChoiceSet",
                "id": "leave_type",
                "style": "compact",
                "choices": [
                    {"title": "Богино чөлөө", "value": "day_off"},
                    {"title": "Өвчтэй", "value": "sick"},
                    {"title": "Remote ажиллах", "value": "remote"},
                    {"title": "Ээлжийн амралт", "value": "vacation"},
                    {"title": "Эрүүл мэндийн өдөр", "value": "wellness"},
                    {"title": "Бусад", "value": "other"}
                ]
            }
        ],
        "actions": [
            {"type": "Action.Execute", "title": "Дараах", "verb": "chooseLeaveType", "style": "positive"}
        ]
    }

def create_reason_card():
    """2-р шат: Шалтгаан оруулах Adaptive Card"""
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Чөлөөний шалтгаан", "wrap": True},
            {"type": "Input.Text", "id": "reason", "placeholder": "Шалтгаан бичнэ үү", "isMultiline": True}
        ],
        "actions": [
            {"type": "Action.Execute", "title": "Дараах", "verb": "submitLeaveRequest", "style": "positive"}
        ]
    }

def create_date_time_card(parsed_data: Dict, leave_type: Optional[str] = None, reason_text: Optional[str] = None) -> Dict:
    """3-р шат: Парслагдсан мэдээллээс шалтгаалж огноо/цаг асуух Adaptive Card
    - leave_type болон reason-ийг толгой хэсэгт харуулна
    - Цагаар бол өглөөний цагаас эхлэх байдлаар default утгуудыг (09:00 → 09:00 + inactive_hours) оноож өгнө
    - Доор нь нийт цагийг текстээр харуулна
    """
    inactive_hours = int(parsed_data.get("inactive_hours", parsed_data.get("days", 1) * 8))
    days = int(parsed_data.get("days", 1))
    start_date_val = parsed_data.get("start_date")
    end_date_val = parsed_data.get("end_date") or start_date_val

    header: List[Dict] = []
    header.append({"type": "TextBlock", "text": "3. Хугацаа сонгох", "wrap": True, "weight": "Bolder"})
    if leave_type:
        header.append({"type": "TextBlock", "text": f"Чөлөөний төрөл: {leave_type}", "wrap": True})
    if reason_text:
        header.append({"type": "TextBlock", "text": f"Шалтгаан: {reason_text}", "wrap": True})

    body: List[Dict] = header

    if inactive_hours < 8:
        # Цагаар - нэг өдөр, Input.Date + хоёр Input.Time-ийг нэг мөрөнд (ColumnSet) байрлуулна
        # Өглөөний 09:00-оос эхлэх default
        start_hhmm = "09:00"
        try:
            end_hour = 9 + max(1, inactive_hours)
            end_hhmm = f"{min(23, end_hour):02d}:00"
        except Exception:
            end_hhmm = "13:00"

        if start_date_val:
            body.append({"type": "Input.Date", "id": "date", "value": start_date_val})
        else:
            body.append({"type": "Input.Date", "id": "date"})

        body.append({
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {"type": "TextBlock", "text": "Эхлэх цаг", "wrap": True},
                        {"type": "Input.Time", "id": "start_time", "value": start_hhmm}
                    ]
                },
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {"type": "TextBlock", "text": "Дуусах цаг", "wrap": True},
                        {"type": "Input.Time", "id": "end_time", "value": end_hhmm}
                    ]
                }
            ]
        })

        body.append({"type": "TextBlock", "text": f"Нийт: {inactive_hours} цаг", "wrap": True, "spacing": "Medium"})
    else:
        # Хоногоор - өдрүүдийн тоогоор давталт, value-г автоматаар бөглөх
        body.append({"type": "TextBlock", "text": f"Хоногоор чөлөө - {days} өдрийн огноонуудыг шалгана уу", "wrap": True, "weight": "Bolder"})
        # Эхний өдрөөс эхлэн дараалсан өдрүүдийг бөглөх оролдлого
        try:
            if start_date_val:
                start_dt = datetime.strptime(start_date_val, "%Y-%m-%d")
                for i in range(days):
                    day_dt = start_dt + timedelta(days=i)
                    body.append({"type": "Input.Date", "id": f"day_{i+1}", "value": day_dt.strftime("%Y-%m-%d")})
            else:
                for i in range(1, max(1, days) + 1):
                    body.append({"type": "Input.Date", "id": f"day_{i}"})
        except Exception:
            for i in range(1, max(1, days) + 1):
                body.append({"type": "Input.Date", "id": f"day_{i}"})

        body.append({"type": "TextBlock", "text": f"Нийт: {days * 8} цаг", "wrap": True, "spacing": "Medium"})

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
        "actions": [
            {"type": "Action.Execute", "title": "Дараах", "verb": "submitDatesHours", "style": "positive"}
        ]
    }

def create_user_confirmation_card(
    request_id: str,
    leave_type: Optional[str] = None,
    requester_email: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    days: Optional[int] = None,
    inactive_hours: Optional[int] = None,
    hour_from: Optional[str] = None,
    hour_to: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict:
    """4-р шат: Эцсийн баталгаажуулалт (батлах/засварлах/цуцлах)
    Хугацаа ба Шалтгааныг тусдаа блокуудаар харуулна.
    """
    details_section: List[Dict] = []
    details_section.append({"type": "TextBlock", "text": "Баталгаажуулалт", "weight": "Bolder", "size": "Medium"})

    # Чөлөөний төрөл
    if leave_type:
        details_section.append({"type": "TextBlock", "text": f"Чөлөөний төрөл: {leave_type}", "wrap": True})

    # Хугацаа (тусад нь)
    if start_date and end_date:
        dur_text = f"{start_date} - {end_date}"
        if days is not None and inactive_hours is not None:
            dur_text += f" ({days} хоног / {inactive_hours} цаг)"
        elif days is not None:
            dur_text += f" ({days} хоног)"
        elif inactive_hours is not None:
            dur_text += f" ({inactive_hours} цаг)"
        details_section.append({"type": "TextBlock", "text": f"Хугацаа: {dur_text}", "wrap": True})

    # Цагийн чөлөө бол эхлэх цагийг тусад нь харуулах
    if inactive_hours is not None and inactive_hours < 8 and hour_from:
        details_section.append({"type": "TextBlock", "text": f"Эхлэх цаг: {hour_from}", "wrap": True})

    # Шалтгаан (тусад нь)
    if reason is not None:
        details_section.append({"type": "TextBlock", "text": f"Шалтгаан: {reason}", "wrap": True})

    # Planner таск мэдээлэл
    if requester_email:
        try:
            tasks_info = get_user_planner_tasks(requester_email)
            if tasks_info:
                details_section.append({
                    "type": "TextBlock",
                    "text": "Таскууд:",
                    "weight": "Bolder",
                    "spacing": "Medium"
                })
                details_section.append({
                    "type": "TextBlock",
                    "text": tasks_info,
                    "wrap": True
                })
        except Exception as e:
            logger.warning(f"Planner tasks fetch failed in confirmation card: {str(e)}")

    return {
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": details_section,
        "actions": [
            {"type": "Action.Execute", "title": "Баталгаажуулах", "verb": "confirmUserRequest", "data": {"request_id": request_id}, "style": "positive"},
            {"type": "Action.Execute", "title": "Засварлах", "verb": "editUserRequest", "data": {"request_id": request_id}},
            {"type": "Action.Execute", "title": "Цуцлах", "verb": "cancelUserRequest", "data": {"request_id": request_id}, "style": "destructive"}
        ]
    }

async def handle_user_adaptive_card_action(context: TurnContext, payload: Dict):
    """Хэрэглэгчийн wizard урсгалын Adaptive Card action-уудыг боловсруулах"""
    try:
        verb = payload.get("verb") or payload.get("user_action")
        values = payload

        user_id = context.activity.from_property.id
        user_name = getattr(context.activity.from_property, 'name', None)

        pending = load_pending_confirmation(user_id) or {}
        request_data = pending.get("request_data", pending) or {}
        wizard = request_data.get("wizard", {})
        request_id = request_data.get("request_id") or str(uuid.uuid4())

        # 1. Төрөл сонгох
        if verb in ("chooseLeaveType", "choose_leave_type"):
            leave_type = values.get("leave_type")
            if not leave_type:
                await context.send_activity("❌ Төрөл сонгогдоогүй байна.")
                return
            wizard.update({"step": "await_reason", "leave_type": leave_type})
            request_data.update({
                "request_id": request_id,
                "status": "wizard",
                "wizard": wizard,
                "requester_user_id": user_id,
                "requester_name": user_name
            })
            save_pending_confirmation(user_id, request_data)

            # Карт биш, жирийн мессежээр шалтгаан асуух
            await context.send_activity("Шалтгаанаа бичнэ үү.")
            return

        # 2. Шалтгаан илгээх
        if verb in ("submitLeaveRequest", "submit_reason"):
            reason = values.get("reason", "")
            if not reason.strip():
                await context.send_activity("❌ Шалтгаан хоосон байна.")
                return
            wizard.update({"step": "date_time", "reason": reason})
            # GPT-ээр парслах
            parsed = parse_leave_request(reason, user_name or "User")
            wizard["parsed"] = parsed
            request_data.update({"wizard": wizard})
            save_pending_confirmation(user_id, request_data)

            # Дараах карт: огноо/цаг асуух
            card = create_date_time_card(parsed)
            attachment = Attachment(content_type="application/vnd.microsoft.card.adaptive", content=card)
            await context.send_activity(MessageFactory.attachment(attachment))
            return

        # 3. Огноо/цаг баталгаажуулах
        if verb in ("submit_dates_hours", "submitDatesHours"):
            parsed = wizard.get("parsed", {})
            inactive_hours = parsed.get("inactive_hours", parsed.get("days", 1) * 8)
            days = parsed.get("days", 1)

            final = {}
            if inactive_hours < 8:
                date = values.get("date")
                start_time = values.get("start_time")
                end_time = values.get("end_time")
                if not all([date, start_time, end_time]):
                    await context.send_activity("❌ Огноо болон цагийн мэдээллийг бүрэн оруулна уу.")
                    return
                final.update({
                    "start_date": date,
                    "end_date": date,
                    "inactive_hours": max(1, _safe_diff_hours(start_time, end_time)),
                    "days": 1,
                    "hour_from": start_time,
                    "hour_to": end_time
                })
            else:
                selected_days = []
                for i in range(1, max(1, int(days)) + 1):
                    d = values.get(f"day_{i}")
                    if d:
                        selected_days.append(d)
                if not selected_days:
                    await context.send_activity("❌ Наад зах нь нэг огноо сонгоно уу.")
                    return
                selected_days_sorted = sorted(selected_days)
                final.update({
                    "start_date": selected_days_sorted[0],
                    "end_date": selected_days_sorted[-1],
                    "inactive_hours": len(selected_days_sorted) * 8,
                    "days": len(selected_days_sorted)
                })

            # Эцсийн нэгтгэл
            request_data.update({
                "request_id": request_id,
                "requester_user_id": user_id,
                "requester_name": user_name,
                "reason": wizard.get("reason", parsed.get("reason", "day_off")),
                "status": "pending",
                **final
            })
            request_data["wizard"] = {**wizard, **{"step": "confirm"}}
            save_pending_confirmation(user_id, request_data)

            card = create_user_confirmation_card(
                request_id=request_id,
                leave_type=wizard.get("leave_type"),
                requester_email=(load_user_info(user_id) or {}).get("email"),
                start_date=request_data['start_date'],
                end_date=request_data['end_date'],
                days=request_data['days'],
                inactive_hours=request_data['inactive_hours'],
                hour_from=request_data.get('hour_from'),
                hour_to=request_data.get('hour_to'),
                reason=request_data['reason']
            )
            attachment = Attachment(content_type="application/vnd.microsoft.card.adaptive", content=card)
            await context.send_activity(MessageFactory.attachment(attachment))
            return

        # 4. Баталгаажуулах/засварлах/цуцлах
        if verb in ("confirm_user_request",):
            # pending-г унших
            if not request_data.get("start_date"):
                await context.send_activity("❌ Хүсэлтийн мэдээлэл дутуу байна.")
                return

            # Хүсэлт гаргагчийн мэдээлэл
            requester_info = None
            for user in list_all_users():
                if user["user_id"] == user_id:
                    requester_info = user
                    break
            requester_email = requester_info.get("email") if requester_info else None
            if not requester_email:
                await context.send_activity("❌ Таны имэйл тодорхойгүй байна. Эхлээд bot-той чатлана уу.")
                return

            leave_days = request_data.get("days", 1)
            manager_id = get_available_manager_id(requester_email, leave_days)
            # Manager info
            manager_info = None
            if manager_id:
                try:
                    token = get_graph_access_token()
                    if token:
                        users_api = MicrosoftUsersAPI(token)
                        manager_info = users_api.get_user_by_id(manager_id)
                        if not manager_info:
                            try:
                                leader_info = get_user_manager_info(requester_email)
                                manager_email = leader_info.get('mail') if leader_info else None
                                if manager_email:
                                    manager_info = users_api.get_user_by_email(manager_email)
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"Manager info get failed: {str(e)}")

            finalized_request = {
                "request_id": request_id,
                "requester_email": requester_email,
                "requester_name": requester_info.get("user_name", requester_email) if requester_info else user_name,
                "requester_user_id": user_id,
                "start_date": request_data["start_date"],
                "end_date": request_data["end_date"],
                "days": request_data["days"],
                "reason": request_data.get("reason", "day_off"),
                "inactive_hours": request_data.get("inactive_hours", request_data.get("days", 1) * 8),
                "status": "pending",
                "original_message": request_data.get("original_message", "wizard"),
                "created_at": datetime.now().isoformat(),
                "approver_email": manager_info.get("mail") if manager_info else None,
                "approver_user_id": manager_id
            }

            # Хадгалах
            save_leave_request(finalized_request)

            # External API руу дуудлага
            api_result = await call_external_absence_api(finalized_request)
            if api_result.get("success") and api_result.get("absence_id"):
                finalized_request["absence_id"] = api_result["absence_id"]
                save_leave_request(finalized_request)
                save_user_absence_id(user_id, api_result["absence_id"])

            # Менежер рүү илгээх
            await send_approved_request_to_manager(finalized_request, request_data.get("original_message", "wizard"))

            # Pending wizard устгах ба дараагийн карт (invokeResponse/message) аль хэдийн хэрэглэгчид мэдээлэл өгч байгаа тул
            delete_pending_confirmation(user_id)
            return

        if verb in ("edit_user_request",):
            # Дахин төрөл сонгохоос эхлүүлнэ
            card = create_leave_type_card()
            attachment = Attachment(content_type="application/vnd.microsoft.card.adaptive", content=card)
            await context.send_activity(MessageFactory.attachment(attachment))
            # Wizard дахин эхлүүлэх
            new_data = {"request_id": str(uuid.uuid4()), "status": "wizard", "wizard": {"step": "choose_type"}}
            save_pending_confirmation(user_id, new_data)
            return

        if verb in ("cancel_user_request",):
            delete_pending_confirmation(user_id)
            await context.send_activity("🚫 Хүсэлт цуцлагдлаа.")
            return

        # Аль ч биш бол үл тоомсорлох
        logger.info(f"Unhandled user adaptive card verb: {verb}")
    except Exception as e:
        logger.error(f"Error in handle_user_adaptive_card_action: {str(e)}")
        await context.send_activity(f"❌ Алдаа: {str(e)}")

async def handle_user_adaptive_card_action_invoke(context: TurnContext, payload: Dict, user_id: str, user_name: Optional[str]) -> Optional[Dict]:
    """Sequential Workflow (Action.Execute) - invokeResponse-д буцаах Adaptive Card-ыг үүсгэнэ.
    Буцах утга: дараагийн шатны Adaptive Card (эсвэл None бол богино текст карт)."""
    try:
        verb = payload.get("verb") or payload.get("user_action")
        values = payload

        pending = load_pending_confirmation(user_id) or {}
        request_data = pending.get("request_data", pending) or {}
        wizard = request_data.get("wizard", {})
        request_id = request_data.get("request_id") or str(uuid.uuid4())

        # 1. Төрөл сонгох → Шалтгаан карт буцаах
        if verb in ("chooseLeaveType", "choose_leave_type"):
            leave_type = values.get("leave_type")
            if not leave_type:
                return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "❌ Төрөл сонгогдоогүй байна."}]} 
            wizard.update({"step": "reason", "leave_type": leave_type})
            request_data.update({
                "request_id": request_id,
                "status": "wizard",
                "wizard": wizard,
                "requester_user_id": user_id,
                "requester_name": user_name
            })
            save_pending_confirmation(user_id, request_data)
            return create_reason_card()

        # 2. Шалтгаан → Огноо/цаг карт буцаах
        if verb in ("submitLeaveRequest", "submit_reason"):
            reason = values.get("reason", "")
            if not reason.strip():
                return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "❌ Шалтгаан хоосон байна."}]} 
            wizard.update({"step": "date_time", "reason": reason})
            parsed = parse_leave_request(reason, user_name or "User")
            wizard["parsed"] = parsed
            request_data.update({"wizard": wizard})
            save_pending_confirmation(user_id, request_data)
            return create_date_time_card(parsed, leave_type=wizard.get("leave_type"), reason_text=reason)

        # 3. Огноо/цаг → Баталгаажуулах карт буцаах
        if verb in ("submitDatesHours", "submit_dates_hours"):
            parsed = wizard.get("parsed", {})
            inactive_hours = parsed.get("inactive_hours", parsed.get("days", 1) * 8)
            days = parsed.get("days", 1)

            final = {}
            if inactive_hours < 8:
                date = values.get("date")
                start_time = values.get("start_time")
                end_time = values.get("end_time")
                if not all([date, start_time, end_time]):
                    return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "❌ Огноо болон цагийн мэдээллийг бүрэн оруулна уу."}]} 
                final.update({
                    "start_date": date,
                    "end_date": date,
                    "inactive_hours": max(1, _safe_diff_hours(start_time, end_time)),
                    "days": 1,
                    "hour_from": start_time,
                    "hour_to": end_time
                })
            else:
                selected_days = []
                for i in range(1, max(1, int(days)) + 1):
                    d = values.get(f"day_{i}")
                    if d:
                        selected_days.append(d)
                if not selected_days:
                    return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "❌ Наад зах нь нэг огноо сонгоно уу."}]} 
                selected_days_sorted = sorted(selected_days)
                final.update({
                    "start_date": selected_days_sorted[0],
                    "end_date": selected_days_sorted[-1],
                    "inactive_hours": len(selected_days_sorted) * 8,
                    "days": len(selected_days_sorted)
                })

            request_data.update({
                "request_id": request_id,
                "requester_user_id": user_id,
                "requester_name": user_name,
                "reason": wizard.get("reason", parsed.get("reason", "day_off")),
                "status": "pending",
                **final
            })
            request_data["wizard"] = {**wizard, **{"step": "confirm"}}
            save_pending_confirmation(user_id, request_data)

            user_info = load_user_info(user_id) or {}
            return create_user_confirmation_card(
                request_id=request_id,
                leave_type=wizard.get("leave_type"),
                requester_email=user_info.get("email"),
                start_date=request_data['start_date'],
                end_date=request_data['end_date'],
                days=request_data['days'],
                inactive_hours=request_data['inactive_hours'],
                hour_from=request_data.get('hour_from'),
                hour_to=request_data.get('hour_to'),
                reason=request_data['reason']
            )

        # 4. Баталгаажуулах/засварлах/цуцлах
        if verb in ("confirmUserRequest", "confirm_user_request"):
            # Pending-ээс авах
            pending2 = load_pending_confirmation(user_id) or {}
            rd = pending2.get("request_data", pending2) or {}
            if not rd.get("start_date"):
                return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "❌ Хүсэлтийн мэдээлэл дутуу байна."}]}

            # Хүсэлт гаргагчийн мэдээлэл
            requester_info = None
            for user in list_all_users():
                if user["user_id"] == user_id:
                    requester_info = user
                    break
            requester_email = requester_info.get("email") if requester_info else None
            if not requester_email:
                return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "❌ Таны имэйл тодорхойгүй байна."}]}

            # Менежер тодорхойлох
            leave_days = rd.get("days", 1)
            manager_id = get_available_manager_id(requester_email, leave_days)
            manager_info = None
            if manager_id:
                try:
                    token = get_graph_access_token()
                    if token:
                        users_api = MicrosoftUsersAPI(token)
                        manager_info = users_api.get_user_by_id(manager_id)
                        if not manager_info:
                            try:
                                leader_info = get_user_manager_info(requester_email)
                                manager_email = leader_info.get('mail') if leader_info else None
                                if manager_email:
                                    manager_info = users_api.get_user_by_email(manager_email)
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"Manager info get failed: {str(e)}")

            finalized_request = {
                "request_id": rd.get("request_id") or str(uuid.uuid4()),
                "requester_email": requester_email,
                "requester_name": requester_info.get("user_name", requester_email) if requester_info else user_name,
                "requester_user_id": user_id,
                "start_date": rd["start_date"],
                "end_date": rd["end_date"],
                "days": rd["days"],
                "reason": rd.get("reason", "day_off"),
                "inactive_hours": rd.get("inactive_hours", rd.get("days", 1) * 8),
                "status": "pending",
                "original_message": rd.get("original_message", "wizard"),
                "created_at": datetime.now().isoformat(),
                "approver_email": manager_info.get("mail") if manager_info else None,
                "approver_user_id": manager_id
            }

            # Хадгалах
            save_leave_request(finalized_request)

            # External систем рүү илгээх
            api_result = await call_external_absence_api(finalized_request)
            if api_result.get("success") and api_result.get("absence_id"):
                finalized_request["absence_id"] = api_result["absence_id"]
                save_leave_request(finalized_request)
                save_user_absence_id(user_id, api_result["absence_id"])

            # Менежер рүү илгээх
            await send_approved_request_to_manager(finalized_request, rd.get("reason", "wizard"))

            # Pending wizard устгах (мессеж давхардахгүй)
            delete_pending_confirmation(user_id)
            # invoke-д карт буцаах нь хангалттай; давхар текст мессеж бүү илгээ
            return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "Менежерийн зөвшөөрөл хүлээгдэж байна."}]}
        if verb in ("editUserRequest", "edit_user_request"):
            # Дахин эхний карт буцаах
            new_data = {"request_id": str(uuid.uuid4()), "status": "wizard", "wizard": {"step": "choose_type"}}
            save_pending_confirmation(user_id, new_data)
            return create_leave_type_card()
        if verb in ("cancelUserRequest", "cancel_user_request"):
            delete_pending_confirmation(user_id)
            return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "Хүсэлт цуцлагдлаа."}]}

        return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": "Ойлгосонгүй."}]}
    except Exception as e:
        logger.error(f"Error in handle_user_adaptive_card_action_invoke: {str(e)}")
        return {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": f"❌ Алдаа: {str(e)}"}]}

def _safe_diff_hours(start_time_str: str, end_time_str: str) -> int:
    """HH:MM -> HH:MM цагийн зөрүүг цаг болгож буцаана (доод тал нь 1)."""
    try:
        start_h, start_m = [int(x) for x in start_time_str.split(":", 1)]
        end_h, end_m = [int(x) for x in end_time_str.split(":", 1)]
        start_total = start_h * 60 + start_m
        end_total = end_h * 60 + end_m
        diff_min = max(0, end_total - start_total)
        return max(1, diff_min // 60)  # Дор хаяж 1 цаг
    except Exception:
        return 1

async def handle_adaptive_card_action(context: TurnContext, action_data):
    """Adaptive card action-уудыг handle хийх"""
    try:
        action = action_data.get("action")
        request_id = action_data.get("request_id")
        
        if not action or not request_id:
            await context.send_activity("❌ Алдаатай хүсэлт")
            return

        # Leave request мэдээлэл унших
        request_data = load_leave_request(request_id)
        if not request_data:
            await context.send_activity("❌ Хүсэлт олдсонгүй")
            return

        # Disabled card үүсгэх
        def create_disabled_card(action_type):
            """Товчнууд идэвхгүй болсон card үүсгэх"""
            if action_type == "approve":
                status_text = "✅ ЗӨВШӨӨРӨГДСӨН"
                status_color = "good"
            else:
                status_text = "❌ ТАТГАЛЗАГДСАН"
                status_color = "attention"
            
            card = {
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "🏖️ Чөлөөний хүсэлт",
                        "weight": "bolder",
                        "size": "large",
                        "color": "accent"
                    },
                    {
                        "type": "TextBlock",
                        "text": status_text,
                        "weight": "bolder",
                        "color": status_color,
                        "size": "medium"
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            {
                                "title": "Хүсэлт гаргагч:",
                                "value": request_data.get("requester_name", "N/A")
                            },
                            {
                                "title": "Эхлэх өдөр:",
                                "value": request_data.get("start_date", "N/A")
                            },
                            {
                                "title": "Дуусах өдөр:",
                                "value": request_data.get("end_date", "N/A")
                            },
                            {
                                "title": "Хоногийн тоо:",
                                "value": str(request_data.get("days", "N/A"))
                            },
                            {
                                "title": "Цагийн тоо:",
                                "value": f"{request_data.get('inactive_hours', 'N/A')} цаг"
                            },
                            {
                                "title": "Шалтгаан:",
                                "value": request_data.get("reason", "Тодорхойгүй")
                            },
                            {
                                "title": "Боловсруулсан:",
                                "value": datetime.now().strftime("%Y-%m-%d %H:%M")
                            }
                        ]
                    }
                ],
                "actions": [
                    {
                        "type": "Action.Submit",
                        "title": "✅ Зөвшөөрөх",
                        "data": {
                            "action": "approve",
                            "request_id": request_data.get("request_id")
                        },
                        "style": "positive",
                        "isEnabled": False
                    },
                    {
                        "type": "Action.Submit", 
                        "title": "❌ Татгалзах",
                        "data": {
                            "action": "reject",
                            "request_id": request_data.get("request_id")
                        },
                        "style": "destructive",
                        "isEnabled": False
                    }
                ]
            }
            return card

        # Approval status шинэчлэх
        if action == "approve":
            request_data["status"] = "approved"
            request_data["approved_at"] = datetime.now().isoformat()
            request_data["approved_by"] = context.activity.from_property.id
            
            # Manager хариу өгсөн тул 2 цагийн timer цуцлах
            cancel_manager_response_timer(request_id)
            
            # Орлон ажиллах хүний мэдээлэл авах (adaptive card-аас)
            replacement_email = None
            replacement_result = None
            selected_task_ids = []
            
            if hasattr(context.activity, 'value') and context.activity.value:
                replacement_email = context.activity.value.get('replacement_email', '').strip()
                
                # Сонгогдсон таскуудыг авах
                for key, value in context.activity.value.items():
                    if key.startswith("task_") and value == "true":
                        selected_task_ids.append(key)
                
                if replacement_email:
                    logger.info(f"Орлон ажиллах хүний и-мэйл оруулсан: {replacement_email}")
                    logger.info(f"Сонгогдсон таскууд: {selected_task_ids}")
                    
                    # Орлон ажиллах хүн томилох
                    replacement_result = assign_replacement_worker(
                        request_data.get('requester_email', ''), 
                        replacement_email
                    )
                    
                    if replacement_result["success"]:
                        logger.info(f"Орлон ажиллах хүн амжилттай томилогдлоо: {replacement_email}")
                        request_data["replacement_worker"] = {
                            "email": replacement_email,
                            "assigned_at": datetime.now().isoformat(),
                            "assigned_by": context.activity.from_property.id
                        }
                        
                        # Сонгогдсон таскуудыг sponsor дээр assign хийх
                        if selected_task_ids:
                            task_assign_result = await assign_selected_tasks_to_sponsor(
                                request_data.get('requester_email', ''), 
                                replacement_email, 
                                selected_task_ids,
                                request_data  # Чөлөөний хугацааны мэдээллийг дамжуулах
                            )
                            replacement_result["task_assign"] = task_assign_result
                            logger.info(f"Task assign result: {task_assign_result}")
                    else:
                        logger.error(f"Орлон ажиллах хүн томилоход алдаа: {replacement_result['message']}")
                else:
                    logger.info("Орлон ажиллах хүний и-мэйл оруулаагүй")
            else:
                logger.info("Adaptive card value олдсонгүй")
            
            # External API руу approval дуудлага хийх
            approval_api_result = None
            if request_data.get("absence_id"):
                approval_api_result = await call_approve_absence_api(
                    request_data["absence_id"], 
                    "Зөвшөөрсөн"
                )
                if approval_api_result["success"]:
                    logger.info(f"External API approval successful for absence_id: {request_data['absence_id']}")
                else:
                    logger.error(f"External API approval failed: {approval_api_result.get('message', 'Unknown error')}")
            else:
                logger.warning(f"No absence_id found for request {request_id}, skipping external approval")
            
            # Хүсэлт хадгалах
            save_leave_request(request_data)
            
            # Teams webhook руу мэдэгдэл илгээх (орлон ажиллах хүний мэдээлэлтэй)
            replacement_worker_name = None
            task_transfer_info = None
            if replacement_result and replacement_result["success"]:
                replacement_worker_name = replacement_result['replacement']['name']
                # Таск шилжүүлэх мэдээллийг авах
                if "task_assign" in replacement_result:
                    task_assign = replacement_result["task_assign"]
                    if task_assign.get("success"):
                        task_transfer_info = f"{task_assign['success_count']} таск шилжүүлэгдлээ"
                        # Чөлөөний хугацааны мэдээлэл нэмэх
                        if task_assign.get("leave_duration_seconds"):
                            leave_days = task_assign["leave_duration_seconds"] // (24 * 3600)
                            task_transfer_info += f" (чөлөөний хугацаанд: {leave_days} хоног)"
                    else:
                        task_transfer_info = f"Таск шилжүүлэхэд алдаа: {task_assign.get('message', 'Unknown error')}"
                elif "task_transfer" in replacement_result:
                    task_transfer_info = replacement_result["task_transfer"]
            
            webhook_result = await send_teams_webhook_notification(
                request_data["requester_name"], 
                replacement_worker_name,
                request_data,
                task_transfer_info
            )
            webhook_status_msg = ""
            if webhook_result["success"]:
                # webhook_status_msg = "\n📢 Teams-д мэдэгдэл илгээгдлээ"
                webhook_status_msg = ""
            else:
                # webhook_status_msg = f"\n⚠️ Teams мэдэгдэлд алдаа: {webhook_result.get('message', 'Unknown error')}"
                webhook_status_msg = ""
            
            # Disabled card илгээх
            disabled_card = create_disabled_card("approve")
            adaptive_card_attachment = Attachment(
                content_type="application/vnd.microsoft.card.adaptive",
                content=disabled_card
            )
            disabled_message = MessageFactory.attachment(adaptive_card_attachment)
            await context.send_activity(disabled_message)
            
            # Хүсэлт гаргагч руу мэдэгдэх
            requester_conversation = load_conversation_reference(request_data["requester_user_id"])
            if requester_conversation:
                async def notify_approval(ctx: TurnContext):
                    approval_status_msg = ""
                    if approval_api_result:
                        if approval_api_result["success"]:
                            # approval_status_msg = "\n✅ PMT дээр орлоо."
                            approval_status_msg = ""
                        else:
                            approval_status_msg = f"\n⚠️ Системд зөвшөөрөхэд алдаа: {approval_api_result.get('message', 'Unknown error')}"
                    
                    # Орлон ажиллах хүний мэдээлэл нэмэх
                    replacement_info = ""
                    task_transfer_info = ""
                    if replacement_result and replacement_result["success"]:
                        replacement_info = f"\n🔄 Орлон ажиллах хүн: {replacement_result['replacement']['name']} ({replacement_result['replacement']['email']})"
                        # Таск шилжүүлэх мэдээллийг нэмэх
                        if "task_assign" in replacement_result:
                            task_assign = replacement_result["task_assign"]
                            if task_assign.get("success"):
                                task_transfer_info = f"\n📋 {task_assign['success_count']} таск орлон ажиллах хүнд шилжүүлэгдлээ"
                                # Чөлөөний хугацааны мэдээлэл нэмэх
                                if task_assign.get("leave_duration_seconds"):
                                    leave_days = task_assign["leave_duration_seconds"] // (24 * 3600)
                                    task_transfer_info += f" (чөлөөний хугацаанд: {leave_days} хоног)"
                            else:
                                task_transfer_info = f"\n⚠️ Таск шилжүүлэхэд алдаа: {task_assign.get('message', 'Unknown error')}"
                        elif "task_transfer" in replacement_result:
                            task_transfer_info = f"\n📋 Таск шилжүүлэлт: {replacement_result['task_transfer']}"
                    elif replacement_email and replacement_result and not replacement_result["success"]:
                        replacement_info = f"\n⚠️ Орлон ажиллах хүн томилоход алдаа: {replacement_result['message']}"
                    
                    await ctx.send_activity(f"🎉 Таны чөлөөний хүсэлт зөвшөөрөгдлөө!\n📅 {request_data['start_date']} - {request_data['end_date']} ({request_data['days']} хоног)\n✨ Сайхан амраарай!{approval_status_msg}{webhook_status_msg}{replacement_info}{task_transfer_info}")

                await ADAPTER.continue_conversation(
                    requester_conversation,
                    notify_approval,
                    app_id
                )
            
        elif action == "reject":
            # Manager хариу өгсөн тул 2 цагийн timer цуцлах
            cancel_manager_response_timer(request_id)
            
            # Manager-ээс татгалзах шалтгаан асуух
            manager_user_id = context.activity.from_property.id
            save_pending_rejection(manager_user_id, request_data)
            
            # Manager-д шалтгаан асуух
            await context.send_activity(f"❓ Татгалзах шалтгааныг бичнэ үү:\n\n📝 Хүсэлт: {request_data['requester_name']} - {request_data['start_date']} ({request_data['days']} хоног)\n💭 Шалтгаан: {request_data['reason']}\n\n✍️ Татгалзах шалтгааныг дараагийн мессежээр илгээнэ үү...")
            
        logger.info(f"Leave request {request_id} {action}d by {context.activity.from_property.id}")
        
    except Exception as e:
        logger.error(f"Error handling adaptive card action: {str(e)}")
        await context.send_activity(f"❌ Алдаа гарлаа: {str(e)}")

@app.route("/proactive-message", methods=["POST"])
def proactive_message():
    data = request.json
    message_text = data.get("message", "Сайн байна уу!")
    user_id = data.get("user_id")  # Тодорхой хэрэглэгч рүү мессеж илгээх
    
    try:
        if user_id:
            # Тодорхой хэрэглэгч рүү мессеж илгээх
            conversation_reference = load_conversation_reference(user_id)
            if not conversation_reference:
                return jsonify({"error": f"User {user_id} not found"}), 404
        else:
            # Хуучин арга: conversation_reference.json файлаас унших
            try:
                with open("conversation_reference.json", "r", encoding="utf-8") as f:
                    ref_data = json.load(f)
                conversation_reference = ConversationReference().deserialize(ref_data)
            except FileNotFoundError:
                return jsonify({"error": "No conversation reference found. Please specify user_id or ensure at least one user has messaged the bot."}), 404
        
        # Дэлгэрэнгүй log
        logger.info("=== Proactive message info ===")
        logger.info(f"User ID: {conversation_reference.user.id}")
        logger.info(f"User Name: {getattr(conversation_reference.user, 'name', None)}")
        logger.info(f"Conversation ID: {conversation_reference.conversation.id}")
        logger.info(f"Conversation Type: {getattr(conversation_reference.conversation, 'conversation_type', None)}")
        logger.info(f"Service URL: {conversation_reference.service_url}")
        logger.info(f"Bot ID: {conversation_reference.bot.id}")
        logger.info(f"Tenant ID: {getattr(conversation_reference.conversation, 'tenant_id', None)}")
        logger.info(f"Channel ID: {conversation_reference.channel_id}")
        logger.info(f"Message to send: {message_text}")
        
        async def send_proactive(context: TurnContext):
            await context.send_activity(message_text)
        
        asyncio.run(
            ADAPTER.continue_conversation(
                conversation_reference,
                send_proactive,
                app_id
            )
        )
        logger.info("Proactive message sent successfully")
        return jsonify({"status": "ok", "user_id": conversation_reference.user.id}), 200
    except Exception as e:
        logger.error(f"Proactive message error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/broadcast", methods=["POST"])
def broadcast_message():
    """Бүх хэрэглэгч рүү мессеж илгээх"""
    data = request.json
    message_text = data.get("message", "Сайн байна уу!")
    
    users = list_all_users()
    if not users:
        return jsonify({"error": "No users found"}), 404
    
    results = []
    for user_info in users:
        user_id = user_info["user_id"]
        try:
            conversation_reference = load_conversation_reference(user_id)
            if conversation_reference:
                async def send_proactive(context: TurnContext):
                    await context.send_activity(message_text)
                
                asyncio.run(
                    ADAPTER.continue_conversation(
                        conversation_reference,
                        send_proactive,
                        app_id
                    )
                )
                results.append({
                    "user_id": user_id,
                    "email": user_info.get("email"),
                    "user_name": user_info.get("user_name"),
                    "status": "success"
                })
                logger.info(f"Message sent to user {user_id} ({user_info.get('email', 'No email')})")
            else:
                results.append({
                    "user_id": user_id,
                    "email": user_info.get("email"),
                    "user_name": user_info.get("user_name"),
                    "status": "failed",
                    "error": "Reference not found"
                })
        except Exception as e:
            results.append({
                "user_id": user_id,
                "email": user_info.get("email"),
                "user_name": user_info.get("user_name"),
                "status": "failed",
                "error": str(e)
            })
            logger.error(f"Failed to send message to user {user_id}: {str(e)}")
    
    return jsonify({"results": results, "total_users": len(users), "message": message_text}), 200

@app.route("/send-by-conversation", methods=["POST"])
def send_by_conversation():
    """Conversation ID-аар мессеж илгээх"""
    try:
        data = request.json
        conversation_id = data.get("conversation_id")
        message_text = data.get("message", "Сайн байна уу!")

        if not conversation_id:
            return jsonify({"error": "conversation_id is required"}), 400

        # Conversation ID-аар хэрэглэгч олох
        user_info = find_user_by_conversation_id(conversation_id)
        if not user_info:
            return jsonify({"error": f"User with conversation_id {conversation_id} not found"}), 404

        # Conversation reference унших
        conversation_reference = load_conversation_reference(user_info["user_id"])
        if not conversation_reference:
            return jsonify({"error": "Conversation reference not found"}), 404

        # Мессеж илгээх
        async def send_message(context: TurnContext):
            await context.send_activity(message_text)

        asyncio.run(
            ADAPTER.continue_conversation(
                conversation_reference,
                send_message,
                app_id
            )
        )

        logger.info(f"Message sent to conversation {conversation_id} (user: {user_info.get('email', 'N/A')})")
        return jsonify({
            "status": "success",
            "conversation_id": conversation_id,
            "user_email": user_info.get("email"),
            "user_name": user_info.get("user_name"),
            "message": message_text
        }), 200

    except Exception as e:
        logger.error(f"Send by conversation error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

@app.route("/approval-callback", methods=["POST"])
def approval_callback():
    """Adaptive card approval callback (backup endpoint)"""
    try:
        data = request.json
        action = data.get("action")
        request_id = data.get("request_id")
        
        logger.info(f"Approval callback: {action} for request {request_id}")
        
        return jsonify({"status": "received", "action": action, "request_id": request_id}), 200
    except Exception as e:
        logger.error(f"Approval callback error: {str(e)}")
        return jsonify({"error": str(e)}), 500

def save_pending_confirmation(user_id, request_data):
    """Хэрэглэгчийн баталгаажуулалтыг хүлээж буй мэдээллийг хадгалах"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_{safe_user_id}.json"
        
        confirmation_data = {
            "user_id": user_id,
            "request_data": request_data,
            "created_at": datetime.now().isoformat(),
            "status": "awaiting_confirmation",
            "timeout_seconds": CONFIRMATION_TIMEOUT_SECONDS
        }
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(confirmation_data, f, ensure_ascii=False, indent=2)
        
        # 30 минутын timeout timer эхлүүлэх
        start_confirmation_timer(user_id)
        
        logger.info(f"Saved pending confirmation for user {user_id} with {CONFIRMATION_TIMEOUT_SECONDS}s timeout")
        return True
    except Exception as e:
        logger.error(f"Failed to save pending confirmation: {str(e)}")
        return False

def load_pending_confirmation(user_id):
    """Хэрэглэгчийн баталгаажуулалтыг хүлээж буй мэдээллийг унших"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load pending confirmation for user {user_id}: {str(e)}")
        return None

def delete_pending_confirmation(user_id):
    """Хэрэглэгчийн баталгаажуулалтыг хүлээж буй мэдээллийг устгах"""
    try:
        safe_user_id = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_{safe_user_id}.json"
        
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"Deleted pending confirmation for user {user_id}")
        
        # Timer цуцлах
        cancel_confirmation_timer(user_id)
        return True
    except Exception as e:
        logger.error(f"Failed to delete pending confirmation: {str(e)}")
        return False

def start_confirmation_timer(user_id):
    """Хэрэглэгчийн баталгаажуулалтын timeout timer эхлүүлэх"""
    try:
        # Хуучин timer байвал цуцлах
        cancel_confirmation_timer(user_id)
        
        # Шинэ timer үүсгэх
        timer = threading.Timer(CONFIRMATION_TIMEOUT_SECONDS, handle_confirmation_timeout, args=[user_id])
        timer.start()
        active_timers[user_id] = timer
        
        logger.info(f"Started {CONFIRMATION_TIMEOUT_SECONDS}s confirmation timer for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to start confirmation timer for user {user_id}: {str(e)}")
        return False

def cancel_confirmation_timer(user_id):
    """Хэрэглэгчийн баталгаажуулалтын timer цуцлах"""
    try:
        if user_id in active_timers:
            timer = active_timers[user_id]
            timer.cancel()
            del active_timers[user_id]
            logger.info(f"Cancelled confirmation timer for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to cancel confirmation timer for user {user_id}: {str(e)}")
        return False

def handle_confirmation_timeout(user_id):
    """Баталгаажуулалтын timeout болоход дуудагдах функц"""
    try:
        logger.info(f"Confirmation timeout for user {user_id}")
        
        # Pending confirmation файл байгаа эсэхийг шалгах
        pending_confirmation = load_pending_confirmation(user_id)
        if not pending_confirmation:
            logger.info(f"No pending confirmation found for user {user_id} - might have been processed already")
            return
        
        request_data = pending_confirmation.get("request_data", {})
        
        # Timeout мессеж илгээх (External API дээр цуцлах шаардлагагүй - absence_id үүсээгүй)
        conversation_reference = load_conversation_reference(user_id)
        if conversation_reference:
            async def send_timeout_message(context: TurnContext):
                await context.send_activity(
                    "⏰ Таны чөлөөний хүсэлтийн баталгаажуулалтын хугацаа (30 минут) дууссан байна.\n\n"
                    "🔄 Шинээр чөлөөний хүсэлт илгээнэ үү. Дэлгэрэнгүй мэдээлэлтэй бичнэ үү."
                )
            
            # Async функцийг sync context-д ажиллуулах
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    ADAPTER.continue_conversation(
                        conversation_reference,
                        send_timeout_message,
                        app_id
                    )
                )
            except Exception as e:
                logger.error(f"Failed to send timeout message to user {user_id}: {str(e)}")
            finally:
                loop.close()
        
        # Manager руу timeout мэдээлэл илгээх шаардлагагүй - absence_id үүсээгүй тул зүгээр л процесс шинээр эхлэнэ
        logger.info(f"Timeout processed - no external API call needed as absence_id was not created yet")
        
        # Pending confirmation устгах
        delete_pending_confirmation(user_id)
        
        logger.info(f"Handled confirmation timeout for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling confirmation timeout for user {user_id}: {str(e)}")

def start_manager_response_timer(request_id, request_data):
    """Manager-ын хариуг хүлээх 2 цагийн timer эхлүүлэх"""
    try:
        # Хуучин timer байвал цуцлах
        cancel_manager_response_timer(request_id)
        
        # Шинэ timer үүсгэх
        timer = threading.Timer(MANAGER_RESPONSE_TIMEOUT_SECONDS, handle_manager_response_timeout, args=[request_id, request_data])
        timer.start()
        manager_pending_actions[request_id] = timer
        
        logger.info(f"Started {MANAGER_RESPONSE_TIMEOUT_SECONDS}s manager response timer for request {request_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to start manager response timer for request {request_id}: {str(e)}")
        return False

def cancel_manager_response_timer(request_id):
    """Manager-ын хариуг хүлээх timer цуцлах"""
    try:
        if request_id in manager_pending_actions:
            timer = manager_pending_actions[request_id]
            timer.cancel()
            del manager_pending_actions[request_id]
            logger.info(f"Cancelled manager response timer for request {request_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to cancel manager response timer for request {request_id}: {str(e)}")
        return False

def handle_manager_response_timeout(request_id, request_data):
    """Manager хариу өгөөгүй 2 цагийн timeout болоход дуудагдах функц"""
    try:
        logger.info(f"Manager response timeout for request {request_id}")
        
        # Timer-ээс устгах
        if request_id in manager_pending_actions:
            del manager_pending_actions[request_id]
        
        # HR Manager-уудад timeout мэдэгдэл илгээх
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                send_manager_timeout_to_hr(request_data)
            )
        except Exception as e:
            logger.error(f"Failed to send manager timeout notification to HR: {str(e)}")
        finally:
            loop.close()
        
        logger.info(f"Handled manager response timeout for request {request_id}")
        
    except Exception as e:
        logger.error(f"Error handling manager response timeout for request {request_id}: {str(e)}")

def save_pending_rejection(manager_user_id, request_data):
    """Manager-н татгалзах шалтгааныг хүлээж буй мэдээллийг хадгалах"""
    try:
        safe_user_id = manager_user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_rejection_{safe_user_id}.json"
        
        rejection_data = {
            "manager_user_id": manager_user_id,
            "request_data": request_data,
            "created_at": datetime.now().isoformat(),
            "status": "awaiting_rejection_reason"
        }
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(rejection_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved pending rejection for manager {manager_user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save pending rejection: {str(e)}")
        return False

def load_pending_rejection(manager_user_id):
    """Manager-н татгалзах шалтгааныг хүлээж буй мэдээллийг унших"""
    try:
        safe_user_id = manager_user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_rejection_{safe_user_id}.json"
        
        if not os.path.exists(filename):
            return None
        
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load pending rejection for manager {manager_user_id}: {str(e)}")
        return None

def delete_pending_rejection(manager_user_id):
    """Manager-н татгалзах шалтгааныг хүлээж буй мэдээллийг устгах"""
    try:
        safe_user_id = manager_user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        filename = f"{PENDING_CONFIRMATIONS_DIR}/pending_rejection_{safe_user_id}.json"
        
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"Deleted pending rejection for manager {manager_user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete pending rejection: {str(e)}")
        return False

def is_confirmation_response(text):
    """Мессеж нь баталгаажуулалтын хариу эсэхийг шалгах"""
    text_lower = text.lower().strip()
    
    # Зөвшөөрөх үгүүд
    approve_words = [
        'тийм', 'зөв', 'yes', 'зөвшөөрнө', 'илгээ', 'ok', 'okay', 
        'зөвшөөрөх', 'баталгаажуулна', 'болно', 'тийм шүү', 'зөв байна', "tiim"
    ]
    
    # Татгалзах үгүүд  
    reject_words = [
        'үгүй', 'буруу', 'no', 'татгалзана', 'битгий', 'болохгүй',
        'засна', 'шинээр', 'дахин', 'өөрчлөх', 'зөв биш', 'ugui', 'ugu', 'gu', 'zasna', 'zasan', 'zasnaa'
    ]
    
    # Цуцлах үгүүд
    cancel_words = [
        'цуцлах', 'цуцлана', 'cancel', 'хүсэхгүй', 'хэрэггүй', 'болиулах', 
        'болиулна', 'цуцал', 'stop', 'битгий', 'авахгүй', 'cuclah', 'cuclana', 'cucel'
    ]
    
    # Цуцлахыг эхэндээ шалгах (илүү тодорхой команд)
    for word in cancel_words:
        if word in text_lower:
            return "cancel"
    
    for word in approve_words:
        if word in text_lower:
            return "approve"
    
    for word in reject_words:
        if word in text_lower:
            return "reject"
    
    return None

def create_confirmation_message(parsed_data, user_email=None):
    """Баталгаажуулалтын мессеж үүсгэх"""
    timeout_minutes = CONFIRMATION_TIMEOUT_SECONDS // 60  # Секундээс минут руу хөрвүүлэх
    
    message = f"""Таны чөлөөний хүсэлт:

📅 **Эхлэх огноо:** {parsed_data.get('start_date')}
📅 **Дуусах огноо:** {parsed_data.get('end_date')}  
⏰ **Хоногийн тоо:** {parsed_data.get('days')} хоног
🕒 **Цагийн тоо:** {parsed_data.get('inactive_hours')} цаг
💭 **Шалтгаан:** {parsed_data.get('reason')}

❓ **Энэ мэдээлэл зөв бөгөөд менежер руу илгээхийг зөвшөөрч байна уу?**

💬 Хариулна уу:
• **"Тийм"** эсвэл **"Үгүй"**
"""
    
    # Planner tasks мэдээлэл нэмэх
    if user_email and PLANNER_AVAILABLE:
        try:
            tasks_info = get_user_planner_tasks(user_email)
            message += f"\n\n{tasks_info}"
        except Exception as e:
            logger.error(f"Failed to add planner tasks to confirmation: {str(e)}")

    return message

async def send_approved_request_to_manager(request_data, original_message):
    """Баталгаажуулсан чөлөөний хүсэлтийг менежер руу илгээх"""
    try:
        # Dynamic manager ID авах - чөлөөний хугацаанаас хамааран тохирох manager-ийг олох
        requester_email = request_data.get('requester_email')
        if requester_email:
            leave_days = request_data.get('days', 1)  # Чөлөөний хоногийн тоо
            manager_id = get_available_manager_id(requester_email, leave_days)
            logger.info(f"Using available manager ID for {requester_email}: {manager_id}")
        else:
            manager_id = None
            logger.warning("No requester email found, cannot get manager ID")
        
        approver_conversation = load_conversation_reference(manager_id) if manager_id else None
        
        if approver_conversation:
            # Adaptive card үүсгэх
            approval_card = create_approval_card(request_data)
            
            async def notify_manager_with_card(ctx: TurnContext):
                adaptive_card_attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=approval_card
                )
                # Planner tasks мэдээлэл авах
                planner_info = ""
                if request_data.get("requester_email"):
                    try:
                        planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                    except Exception as e:
                        logger.error(f"Failed to get planner tasks for approved request: {str(e)}")
                
                # Орлон ажиллах хүний мэдээлэл нэмэх (manager-д мэдэгдэхэд)
                replacement_info_for_manager = ""
                if request_data.get("replacement_worker"):
                    replacement_worker = request_data["replacement_worker"]
                    replacement_info_for_manager = f"\n🔄 Орлон ажиллах хүн томилогдсон: {replacement_worker['email']}"
                
                message = MessageFactory.attachment(adaptive_card_attachment)
                # message.text = f"📨 Баталгаажсан чөлөөний хүсэлт: {request_data['requester_name']}\n💬 Анхны мессеж: \"{original_message}\"\n✅ Хэрэглэгч баталгаажуулсан{replacement_info_for_manager}{planner_info}"
                message.text = f"📨 Чөлөөний хүсэлт"
                await ctx.send_activity(message)
            
            await ADAPTER.continue_conversation(
                approver_conversation,
                notify_manager_with_card,
                app_id
            )
            
            # Manager-ын хариуг хүлээх 2 цагийн timer эхлүүлэх
            start_manager_response_timer(request_data['request_id'], request_data)
            
            logger.info(f"Approved leave request {request_data['request_id']} sent to manager with 2-hour response timer")
        else:
            logger.warning(f"Manager conversation reference not found for request {request_data['request_id']}")
    except Exception as e:
        logger.error(f"Error sending approved request to manager: {str(e)}")

async def send_cancellation_to_manager(request_data, original_message, cancellation_api_result=None):
    """Цуцалсан чөлөөний хүсэлтийг менежер руу мэдэгдэх"""
    try:
        # Dynamic manager ID авах - чөлөөний хугацаанаас хамааран тохирох manager-ийг олох
        requester_email = request_data.get('requester_email')
        if requester_email:
            leave_days = request_data.get('days', 1)  # Чөлөөний хоногийн тоо
            manager_id = get_available_manager_id(requester_email, leave_days)
            logger.info(f"Using available manager ID for {requester_email}: {manager_id}")
        else:
            manager_id = None
            logger.warning("No requester email found, cannot get manager ID")
        
        approver_conversation = load_conversation_reference(manager_id) if manager_id else None
        
        if approver_conversation:
            async def notify_manager_cancellation(ctx: TurnContext):
                # Planner tasks мэдээлэл авах
                planner_info = ""
                if request_data.get("requester_email"):
                    try:
                        planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
                    except Exception as e:
                        logger.error(f"Failed to get planner tasks for cancelled request: {str(e)}")
                
                # API статус мэдээлэл нэмэх
                api_status_info = ""
                if cancellation_api_result:
                    if cancellation_api_result["success"]:
                        api_status_info = "\n✅ **Системээс автоматаар цуцлагдсан**"
                    else:
                        api_status_info = f"\n⚠️ **Системээс цуцлахад алдаа:** {cancellation_api_result.get('message', 'Unknown error')}"
                elif request_data.get("absence_id"):
                    api_status_info = "\n❓ **Системийн статус:** Мэдээлэл алга"
                
                # Цуцлах мэдээлэл
                cancellation_message = f"""🚫 **ЦУЦАЛСАН ЧӨЛӨӨНИЙ ХҮСЭЛТ**

👤 **Хүсэлт гаргагч:** {request_data['requester_name']}
📧 **Имэйл:** {request_data.get('requester_email', 'N/A')}
📅 **Хугацаа:** {request_data['start_date']} - {request_data['end_date']} ({request_data['days']} хоног)
💭 **Шалтгаан байсан:** {request_data['reason']}
💬 **Анхны мессеж:** "{original_message}"

❌ **Хэрэглэгч өөрөө цуцалсан байна**
🕐 **Цуцалсан цаг:** {datetime.now().strftime('%Y-%m-%d %H:%M')}{api_status_info}{planner_info}"""
                
                await ctx.send_activity(cancellation_message)
            
            await ADAPTER.continue_conversation(
                approver_conversation,
                notify_manager_cancellation,
                app_id
            )
            logger.info(f"Cancelled leave request {request_data['request_id']} notification sent to manager")
        else: 
            logger.warning(f"Manager conversation reference not found for cancelled request {request_data['request_id']}")
    except Exception as e:
        logger.error(f"Error sending cancellation to manager: {str(e)}")

# HR руу илгээх үйлдэл хасагдсан - зөвхөн manager timeout үед мэдэгдэх

async def send_manager_timeout_to_hr(request_data):
    """Manager 2 цаг хариу өгөөгүй үед HR Manager-уудад мэдэгдэх"""
    try:
        hr_managers = get_hr_managers()
        
        if not hr_managers:
            logger.warning("HR Manager олдсонгүй - manager timeout мэдэгдэл илгээхгүй")
            return
        
        # Planner tasks мэдээлэл авах
        planner_info = ""
        if request_data.get("requester_email"):
            try:
                planner_info = f"\n\n{get_user_planner_tasks(request_data['requester_email'])}"
            except Exception as e:
                logger.error(f"Failed to get planner tasks for manager timeout: {str(e)}")
        
        # Manager timeout мэдэгдэлийн мессеж
        timeout_hours = MANAGER_RESPONSE_TIMEOUT_SECONDS // 3600  # Секундээс цаг руу хөрвүүлэх
        timeout_message = f"""⏰ **МЕНЕЖЕР ХАРИУ ӨГӨӨГҮЙ - АНХААРАЛ!**

👤 **Хүсэлт гаргагч:** {request_data['requester_name']}
📧 **Имэйл:** {request_data.get('requester_email', 'N/A')}
📅 **Хугацаа:** {request_data['start_date']} - {request_data['end_date']} ({request_data['days']} хоног)
💭 **Шалтгаан:** {request_data['reason']}
💬 **Анхны мессеж:** "{request_data.get('original_message', 'N/A')}"

⚠️ **Асуудал:** Ажлын менежер {timeout_hours} цагийн дотор хариу үйлдэл үзүүлээгүй байна
📤 **Илгээгдсэн огноо:** {request_data.get('created_at', 'N/A')}
🕐 **Одоогийн цаг:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

🔔 **HR-ын үйлдэл:** Менежертэй холбогдож, хүсэлтийн талаар асууна уу.
👨‍💼 **Менежер:** {request_data.get('approver_email', 'N/A')}{planner_info}"""
        
        # HR Manager-уудад timeout мэдэгдэл илгээх
        for hr_manager in hr_managers:
            logger.info(f"Manager timeout мэдэгдэл HR-д: {hr_manager.get('displayName')} ({hr_manager.get('mail')})")
            logger.info(f"Timeout Message: {timeout_message}")
            
        logger.info(f"Manager timeout мэдэгдэл {len(hr_managers)} HR Manager-д илгээгдлээ")
        
        # TODO: Хэрэв HR Manager-уудтай Teams bot conversation байвал тэнд илгээж болно
        # Одоогоор зөвхөн log-д бичиж байна
        
    except Exception as e:
        logger.error(f"Error sending manager timeout notification to HR: {str(e)}")

async def assign_selected_tasks_to_sponsor(requester_email: str, sponsor_email: str, selected_task_ids: List[str], request_data: Dict = None) -> Dict:
    """Сонгогдсон таскуудыг sponsor дээр assign хийх - чөлөөний хугацаанд л"""
    try:
        if not PLANNER_AVAILABLE:
            return {"success": False, "message": "Planner модуль идэвхгүй байна"}
        
        # Access token авах
        token = get_access_token()
        if not token:
            return {"success": False, "message": "Access token авч чадсангүй"}
        
        # Task assignment manager үүсгэх
        task_manager = TaskAssignmentManager(token)
        
        # Хэрэглэгчдийг олох
        requester_user = task_manager.users_api.search_user_by_email(requester_email)
        if not requester_user:
            return {"success": False, "message": f"Чөлөө авсан хүн олдсонгүй: {requester_email}"}
        
        sponsor_user = task_manager.users_api.search_user_by_email(sponsor_email)
        if not sponsor_user:
            return {"success": False, "message": f"Sponsor олдсонгүй: {sponsor_email}"}
        
        # Чөлөөний хугацааг тооцоолох
        leave_duration_seconds = None
        if request_data:
            start_date = datetime.strptime(request_data.get('start_date'), '%Y-%m-%d')
            end_date = datetime.strptime(request_data.get('end_date'), '%Y-%m-%d')
            # Чөлөөний хугацааг секундээр тооцоолох (хугацаа дуусахад + 1 өдөр)
            leave_duration_seconds = (end_date - start_date).days * 24 * 3600 + 24 * 3600  # +1 өдөр
        
        # Сонгогдсон таскуудыг assign хийх
        success_count = 0
        failed_tasks = []
        assigned_tasks = []
        
        for task_id in selected_task_ids:
            try:
                # Task ID-г цэвэрлэх (task_ prefix арилгах)
                clean_task_id = task_id.replace("task_", "")
                
                # Таскыг sponsor дээр assign хийх
                if task_manager.assign_task_to_user(clean_task_id, sponsor_user.get('id')):
                    success_count += 1
                    assigned_tasks.append(clean_task_id)
                    logger.info(f"Task {clean_task_id} амжилттай assign хийгдлээ: {requester_email} -> {sponsor_email}")
                    
                    # Хэрэв чөлөөний хугацаа тодорхой бол автомат unassign тохируулах
                    if leave_duration_seconds:
                        # Чөлөөний хугацаа дуусахад автоматаар unassign хийх
                        task_manager.auto_unassign_after_delay(clean_task_id, sponsor_user.get('id'), leave_duration_seconds)
                        logger.info(f"Task {clean_task_id} {leave_duration_seconds} секундийн дараа автоматаар unassign хийгдэх болно")
                else:
                    failed_tasks.append(clean_task_id)
                    logger.error(f"Task {clean_task_id} assign хийхэд алдаа гарлаа")
            except Exception as e:
                failed_tasks.append(task_id)
                logger.error(f"Task {task_id} assign хийхэд алдаа: {str(e)}")
        
        result = {
            "success": success_count > 0,
            "total_selected": len(selected_task_ids),
            "success_count": success_count,
            "failed_count": len(failed_tasks),
            "failed_tasks": failed_tasks,
            "assigned_tasks": assigned_tasks,
            "leave_duration_seconds": leave_duration_seconds,
            "message": f"{success_count}/{len(selected_task_ids)} таск амжилттай assign хийгдлээ"
        }
        
        if leave_duration_seconds:
            leave_days = leave_duration_seconds // (24 * 3600)
            result["message"] += f" (чөлөөний хугацаанд: {leave_days} хоног)"
        
        if failed_tasks:
            result["message"] += f". Алдаа гарсан таскууд: {', '.join(failed_tasks)}"
        
        return result
        
    except Exception as e:
        logger.error(f"Task assign хийхэд алдаа: {str(e)}")
        return {"success": False, "message": f"Task assign хийхэд алдаа: {str(e)}"}

async def unassign_tasks_on_leave_end(requester_email: str) -> Dict:
    """Чөлөө дуусахад sponsor дээр assign хийгдсэн таскуудыг unassign хийх"""
    try:
        if not PLANNER_AVAILABLE:
            return {"success": False, "message": "Planner модуль идэвхгүй байна"}
        
        # Access token авах
        token = get_access_token()
        if not token:
            return {"success": False, "message": "Access token авч чадсангүй"}
        
        # Task assignment manager үүсгэх
        task_manager = TaskAssignmentManager(token)
        
        # Чөлөө авсан хүнийг олох
        requester_user = task_manager.users_api.search_user_by_email(requester_email)
        if not requester_user:
            return {"success": False, "message": f"Чөлөө авсан хүн олдсонгүй: {requester_email}"}
        
        # Орлон ажиллах хүмүүсийг авах
        replacement_workers_result = get_replacement_workers(requester_email)
        if not replacement_workers_result.get("success"):
            return {"success": False, "message": "Орлон ажиллах хүмүүсийг авах боломжгүй"}
        
        replacement_workers = replacement_workers_result.get("replacement_workers", [])
        if not replacement_workers:
            return {"success": True, "message": "Хасах орлон ажиллах хүн байхгүй", "unassigned_count": 0}
        
        total_unassigned = 0
        unassign_results = []
        
        # Бүх орлон ажиллах хүмүүсээс таскуудыг unassign хийх
        for replacement in replacement_workers:
            try:
                # Орлон ажиллах хүний таскуудыг авах
                replacement_tasks = task_manager.get_user_tasks(replacement.get('id'))
                if not replacement_tasks:
                    continue
                
                # Зөвхөн идэвхтэй таскуудыг unassign хийх
                active_tasks = [task for task in replacement_tasks if task.get('percentComplete', 0) < 100]
                
                unassigned_count = 0
                for task in active_tasks:
                    try:
                        # Таскыг unassign хийх
                        if task_manager.unassign_task_from_user(task.get('id'), replacement.get('id')):
                            unassigned_count += 1
                            logger.info(f"Task {task.get('id')} unassign хийгдлээ: {replacement.get('email')}")
                        else:
                            logger.error(f"Task {task.get('id')} unassign хийхэд алдаа гарлаа")
                    except Exception as e:
                        logger.error(f"Task {task.get('id')} unassign хийхэд алдаа: {str(e)}")
                
                total_unassigned += unassigned_count
                unassign_results.append({
                    "replacement_email": replacement.get('email'),
                    "replacement_name": replacement.get('displayName'),
                    "unassigned_count": unassigned_count
                })
                
            except Exception as e:
                logger.error(f"Replacement {replacement.get('email')} дээрх таскууд unassign хийхэд алдаа: {str(e)}")
        
        return {
            "success": True,
            "total_unassigned": total_unassigned,
            "replacement_count": len(replacement_workers),
            "unassign_results": unassign_results,
            "message": f"{total_unassigned} таск автоматаар unassign хийгдлээ"
        }
        
    except Exception as e:
        logger.error(f"Task unassign хийхэд алдаа: {str(e)}")
        return {"success": False, "message": f"Task unassign хийхэд алдаа: {str(e)}"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)