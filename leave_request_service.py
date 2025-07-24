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
        try:
            config = Config()
            self.openai_key = config.OPENAI_API_KEY
            
            if not self.openai_key:
                print("❌ OpenAI API key тохируулаагүй байна")
                
        except Exception as e:
            print(f"❌ Leave request service эхлүүлэхэд алдаа: {str(e)}")
            self.openai_key = None
        
    def analyze_message_for_leave_request(self, message: str, user_email: str) -> Optional[Dict]:
        """
        Мессежийг шинжилж чөлөөний хүсэлт эсэхийг тодорхойлох
        """
        try:
            if not self.openai_key:
                print("❌ OpenAI API key алга байна")
                return None
                
            client = openai.OpenAI(api_key=self.openai_key)
            
            # NLP prompt for leave request detection
            prompt = f"""
            Дараах мессежийг шинжилж, энэ нь чөлөөний хүсэлт эсэхийг тодорхойлно уу:

            Мессеж: "{message}"

            Энгийн шинжилгээ хий:
            - "chuluu", "чөлөө", "амралт", "өвчин" гэх үгс байна уу?
            - "margaash", "маргааш" гэх огноо байна уу?
            - Энгийн шалтгаан дурдсан уу?

            JSON форматаар буцаа:
            {{
                "is_leave_request": true/false,
                "start_date": "маргаашийн огноо эсвэл огноогүй",
                "end_date": "маргаашийн огноо эсвэл огноогүй", 
                "reason": "дурдсан шалтгаан эсвэл 'энгийн чөлөө'",
                "in_active_hours": 8.0,
                "confidence": 0.9,
                "missing_info": []
            }}

            Жишээ:
            - "margaash chuluu avmaar huviin shaltgaanaar" → 
            {{
                "is_leave_request": true,
                "start_date": "маргааш", 
                "end_date": "маргааш",
                "reason": "хувийн шалтгаан",
                "in_active_hours": 8.0,
                "confidence": 0.95,
                "missing_info": []
            }}

            Хэрэв чөлөө биш бол: {{"is_leave_request": false, "confidence": 0.1}}
            Зөвхөн JSON буцаа.
            """
            
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
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
            if not result.get("start_date") or not result.get("end_date") or not result.get("in_active_hours"):
                dates = self._extract_dates_from_text(original_message)
                if dates:
                    result["start_date"] = dates.get("start_date", result.get("start_date"))
                    result["end_date"] = dates.get("end_date", result.get("end_date"))
                    if dates.get("in_active_hours"):
                        result["in_active_hours"] = dates.get("in_active_hours")
            
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
            
            # Missing info шалгах логик сайжруулах
            missing = []
            if not result.get("start_date") or result.get("start_date") == "огноогүй":
                missing.append("start_date")
            if not result.get("reason") or result.get("reason") == "энгийн чөлөө":
                # Хувийн шалтгаан гэж дурдсан бол хангалттай
                pass
            
            result["missing_info"] = missing
                
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
        """Текстээс огноо болон хугацаа гарган авах"""
        
        # Монгол огноо форматууд + цаг/хоног шинжилгээ
        date_patterns = [
            r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})',  # DD.MM.YYYY
            r'(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})',  # YYYY.MM.DD
            r'(\d{1,2})\s*(сар|сарын)\s*(\d{1,2})',    # 12 сарын 25
        ]
        
        # Цаг/хоног паттерн шинжилгээ
        duration_patterns = [
            r'(\d+)\s*(tsagiin|цагийн|цаг)',           # 8tsagiin, 8 цагийн
            r'(\d+)\s*(honog|хоног)',                  # 1 хоног
            r'(\d+)\s*(udur|өдөр)',                    # 2 өдөр
        ]
        
        # Хугацаа олох
        total_hours = 8.0  # default
        for pattern in duration_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                try:
                    duration = int(matches[0][0])
                    unit = matches[0][1].lower()
                    if 'tsag' in unit or 'цаг' in unit:
                        total_hours = float(duration)
                    elif 'honog' in unit or 'хоног' in unit or 'udur' in unit or 'өдөр' in unit:
                        total_hours = float(duration * 8)  # 8 цаг/өдөр
                except:
                    pass
        
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
                "end_date": dates[-1] if len(dates) > 1 else dates[0],
                "in_active_hours": total_hours
            }
        
        # Хэрэв огноо олдоогүй ч цаг олдсон бол
        if total_hours != 8.0:
            return {
                "in_active_hours": total_hours
            }
        
        return None
    
    def _parse_mongolian_date(self, date_str: str) -> str:
        """Монгол болон транслит огноог parse хийх"""
        
        try:
            today = datetime.now()
            date_lower = date_str.lower().strip()
            
            # Хэрэв аль хэдийн YYYY-MM-DD формат бол шууд буцаах
            if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                return date_str
            
            # Монгол хэл
            if "өнөөдөр" in date_lower or "unuudur" in date_lower:
                return today.strftime("%Y-%m-%d")
            elif "маргааш" in date_lower or "margaash" in date_lower:
                return (today + timedelta(days=1)).strftime("%Y-%m-%d")
            elif "нөгөөдөр" in date_lower or "nuguudur" in date_lower:
                return (today + timedelta(days=2)).strftime("%Y-%m-%d")
            else:
                # Бусад тохиолдолд маргаашийн огноог буцаах (default)
                return (today + timedelta(days=1)).strftime("%Y-%m-%d")
                
        except:
            return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    def generate_follow_up_questions(self, missing_info: List[str]) -> str:
        """Дутуу мэдээллийн төлөө лавлах асуултууд үүсгэх"""
        
        # Зөвхөн чухал мэдээлэл дутуу үед л асуух
        critical_missing = []
        
        if "start_date" in missing_info:
            critical_missing.append("📅 Хэзээнээс эхлэх вэ?")
            
        if "reason" in missing_info:
            critical_missing.append("📝 Ямар шалтгаантай вэ?")
        
        # Хэрэв зөвхөн end_date дутуу бол start_date-тай ижил болгох
        if not critical_missing:
            return ""
            
        header = "🤔 **Нэмэлт мэдээлэл хэрэгтэй:**\n\n"
        question_text = "\n".join(f"• {q}" for q in critical_missing)
        footer = "\n\n💡 *Энгийнээр хариулна уу*"
        
        return header + question_text + footer 