"""
Leave Request Service - NLP ашиглан чөлөөний хүсэлт танидаг
"""

import re
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import openai
from config import Config

class LeaveRequestService:
    """Чөлөөний хүсэлтийг танидаг сервис"""
    
    def __init__(self):
        config = Config()
        self.openai_key = config.OPENAI_API_KEY
        
    def analyze_message_for_leave_request(self, message: str, user_email: str) -> Optional[Dict]:
        """
        Мессежийг шинжилж чөлөөний хүсэлт эсэхийг тодорхойлох
        """
        try:
            client = openai.OpenAI(api_key=self.openai_key)
            
            # NLP prompt for leave request detection
            prompt = f"""
            Монгол хэл дээрх дараах мессежийг шинжилж, энэ нь чөлөөний хүсэлт эсэхийг тодорхой болгоно уу:

            Мессеж: "{message}"

            Хэрэв энэ нь чөлөөний хүсэлт бол дараах мэдээллийг JSON форматаар буцаана:
            {{
                "is_leave_request": true,
                "start_date": "YYYY-MM-DD",
                "end_date": "YYYY-MM-DD", 
                "reason": "шалтгаан",
                "in_active_hours": 8.0,
                "confidence": 0.95
            }}

            Хэрэв чөлөөний хүсэлт биш бол:
            {{
                "is_leave_request": false,
                "confidence": 0.1
            }}

            Анхаарах зүйлс:
            - "чөлөө", "амралт", "өвчин", "гарах", "хүсэлт" гэх мэт үгс
            - Огноо, хугацаа дурдсан эсэх
            - Шалтгаан дурдсан эсэх
            - Зөвхөн JSON буцаана, бусад тайлбар бүү нэм
            """
            
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # JSON парс хийх
            import json
            try:
                result = json.loads(result_text)
                
                if result.get("is_leave_request", False):
                    # User email нэмэх
                    result["user_email"] = user_email
                    
                    # Огноо форматыг шалгах ба засах
                    result = self._validate_and_fix_dates(result, message)
                    
                return result
            except json.JSONDecodeError:
                print(f"JSON parse алдаа: {result_text}")
                return None
                
        except Exception as e:
            print(f"NLP analysis алдаа: {str(e)}")
            return None
    
    def _validate_and_fix_dates(self, result: Dict, original_message: str) -> Dict:
        """Огноонуудыг шалгаж засах"""
        
        try:
            # Хэрэв огноо дутуу бол одоогийн мессежээс гарган авах оролдлого
            if not result.get("start_date") or not result.get("end_date"):
                dates = self._extract_dates_from_text(original_message)
                if dates:
                    result["start_date"] = dates.get("start_date", result.get("start_date"))
                    result["end_date"] = dates.get("end_date", result.get("end_date"))
            
            # Огноо форматыг шалгах
            start_date = result.get("start_date")
            end_date = result.get("end_date")
            
            if start_date:
                # YYYY-MM-DD формат шалгах
                if not re.match(r'\d{4}-\d{2}-\d{2}', start_date):
                    result["start_date"] = self._parse_mongolian_date(start_date)
            
            if end_date:
                if not re.match(r'\d{4}-\d{2}-\d{2}', end_date):
                    result["end_date"] = self._parse_mongolian_date(end_date)
            
            # Хэрэв end_date алга бол start_date-тай ижил болгох
            if not result.get("end_date") and result.get("start_date"):
                result["end_date"] = result["start_date"]
                
            # in_active_hours тооцоолох
            if result.get("start_date") and result.get("end_date"):
                try:
                    start = datetime.strptime(result["start_date"], "%Y-%m-%d")
                    end = datetime.strptime(result["end_date"], "%Y-%m-%d")
                    days = (end - start).days + 1
                    result["in_active_hours"] = days * 8.0  # 8 цаг/өдөр
                except:
                    result["in_active_hours"] = 8.0
                    
        except Exception as e:
            print(f"Date validation алдаа: {str(e)}")
            
        return result
    
    def _extract_dates_from_text(self, text: str) -> Optional[Dict]:
        """Текстээс огноо гарган авах"""
        
        # Монгол огноо форматууд
        date_patterns = [
            r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})',  # DD.MM.YYYY
            r'(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})',  # YYYY.MM.DD
            r'(\d{1,2})\s*(сар|сарын)\s*(\d{1,2})',    # 12 сарын 25
        ]
        
        dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    if len(match) == 3:
                        if 'сар' in pattern:
                            # Монгол формат
                            month, _, day = match
                            year = datetime.now().year
                            date_str = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                        else:
                            # Бусад формат
                            if len(match[0]) == 4:  # YYYY first
                                year, month, day = match
                            else:  # DD first
                                day, month, year = match
                            date_str = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                        
                        dates.append(date_str)
                except:
                    continue
        
        if dates:
            return {
                "start_date": dates[0],
                "end_date": dates[-1] if len(dates) > 1 else dates[0]
            }
        
        return None
    
    def _parse_mongolian_date(self, date_str: str) -> str:
        """Монгол огноог parse хийх"""
        
        try:
            # "Өнөөдөр", "маргааш" гэх мэт
            today = datetime.now()
            
            if "өнөөдөр" in date_str.lower():
                return today.strftime("%Y-%m-%d")
            elif "маргааш" in date_str.lower():
                return (today + timedelta(days=1)).strftime("%Y-%m-%d")
            elif "нөгөөдөр" in date_str.lower():
                return (today + timedelta(days=2)).strftime("%Y-%m-%d")
            else:
                # Бусад тохиолдолд өнөөдрийн огноог буцаах
                return today.strftime("%Y-%m-%d")
                
        except:
            return datetime.now().strftime("%Y-%m-%d") 