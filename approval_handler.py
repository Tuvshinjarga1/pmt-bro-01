"""
Approval Handler - Лидэрийн зөвшөөрөл/татгалзал боловсруулах
"""

import re
from typing import Dict, Optional
from teams_auth_service import TeamsAuthService
from organization_service import OrganizationService

class ApprovalHandler:
    """Лидэрийн зөвшөөрөл/татгалзал боловсруулах сервис"""
    
    def __init__(self):
        self.teams_service = TeamsAuthService()
        self.org_service = OrganizationService()
    
    def process_manager_response(self, manager_email: str, response_text: str) -> bool:
        """
        Лидэрийн хариултыг боловсруулах
        """
        try:
            response_lower = response_text.lower().strip()
            
            # APPROVE патtern шалгах
            approve_match = re.search(r'approve\s+([^\s]+)', response_lower)
            if approve_match:
                user_email = approve_match.group(1)
                return self._process_approval(manager_email, user_email)
            
            # REJECT патtern шалгах  
            reject_match = re.search(r'reject\s+([^\s]+)\s+(.+)', response_lower)
            if reject_match:
                user_email = reject_match.group(1)
                reason = reject_match.group(2)
                return self._process_rejection(manager_email, user_email, reason)
            
            print(f"Тодорхойгүй команд: {response_text}")
            return False
            
        except Exception as e:
            print(f"❌ Manager response боловсруулахад алдаа: {str(e)}")
            return False
    
    def _process_approval(self, manager_email: str, user_email: str) -> bool:
        """Зөвшөөрөл боловсруулах"""
        
        try:
            # Хэрэглэгчийн мэдээлэл авах
            user_profile = self.org_service.get_user_profile(user_email)
            user_name = user_profile.get('displayName', user_email) if user_profile else user_email
            
            # TODO: Энд чөлөөний хүсэлтийн мэдээллийг database-аас авах хэрэгтэй
            # Одоогоор placeholder мэдээлэл ашиглана
            start_date = "2024-12-XX"  # Database-аас авах
            end_date = "2024-12-XX"    # Database-аас авах
            
            # Channel дээр зарлах
            success = self.teams_service.announce_leave_approval(
                user_email, user_name, start_date, end_date
            )
            
            if success:
                print(f"✅ {user_email}-н чөлөө зөвшөөрөгдөж, channel дээр зарлагдлаа")
                
                # TODO: Database дээр чөлөөний статусыг APPROVED болгох
                # TODO: Хэрэглэгчид мэдэгдэл илгээх
                
                return True
            else:
                print(f"❌ Channel дээр зарлахад алдаа гарлаа")
                return False
                
        except Exception as e:
            print(f"❌ Approval боловсруулахад алдаа: {str(e)}")
            return False
    
    def _process_rejection(self, manager_email: str, user_email: str, reason: str) -> bool:
        """Татгалзал боловсруулах"""
        
        try:
            # Хэрэглэгчийн мэдээлэл авах
            user_profile = self.org_service.get_user_profile(user_email)
            user_name = user_profile.get('displayName', user_email) if user_profile else user_email
            
            # Channel дээр зарлах
            success = self.teams_service.announce_leave_rejection(
                user_email, user_name, reason
            )
            
            if success:
                print(f"✅ {user_email}-н чөлөө татгалзагдаж, channel дээр зарлагдлаа")
                
                # TODO: Database дээр чөлөөний статусыг REJECTED болгох
                # TODO: Хэрэглэгчид мэдэгдэл илгээх
                
                return True
            else:
                print(f"❌ Channel дээр зарлахад алдаа гарлаа")
                return False
                
        except Exception as e:
            print(f"❌ Rejection боловсруулахад алдаа: {str(e)}")
            return False
    
    def generate_help_message(self) -> str:
        """Лидэрт зориулсан тусламжийн мессеж"""
        
        return """
🤖 **Чөлөөний хүсэлт удирдах заавар:**

**Зөвшөөрөх:**
`APPROVE user@company.com`

**Татгалзах:** 
`REJECT user@company.com шалтгаан`

**Жишээ:**
• `APPROVE tuvshin@company.com`
• `REJECT tuvshin@company.com ажил их байгаа`

💡 Зөвшөөрсний дараа автоматаар channel дээр зарлагдана.
        """ 