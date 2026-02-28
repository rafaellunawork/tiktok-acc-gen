import random
import time
import json
import re
import string
import structlog
import requests as http_requests
from curl_cffi import requests as curl_requests
from modules.solver import solve_3d_captcha
from modules.mail import ZeusXMail
from urllib.parse import urlencode, quote_plus, urlparse, parse_qs
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uvicorn


class SignerClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def xbogus(self, params, payload, user_agent, timestamp, canvas_fingerprint, mode1, mode2):
        resp = http_requests.post(f"{self.base_url}/xbogus", json={
            "params": params,
            "payload": payload,
            "user_agent": user_agent,
            "timestamp": timestamp,
            "canvas_fingerprint": canvas_fingerprint,
            "mode1": mode1,
            "mode2": mode2,
        })
        return resp.json()["xbogus"]

    def signature(self, url, user_agent):
        resp = http_requests.post(f"{self.base_url}/signature", json={
            "url": url,
            "user_agent": user_agent,
        })
        return resp.json()["signature"]

    def verify(self):
        resp = http_requests.post(f"{self.base_url}/verify")
        return resp.json()["verify_fp"]

    def telemetry_strdata(self):
        resp = http_requests.post(f"{self.base_url}/telemetry_strdata")
        return resp.json()["strdata"]

    def captcha_decrypt(self, edata):
        resp = http_requests.post(f"{self.base_url}/captcha/decrypt", json={
            "edata": edata,
        })
        data = resp.json()
        return data["decrypted"], data["key"], data["nonce"]

    def payment_fingerprint(self, bc_id):
        resp = http_requests.post(f"{self.base_url}/payment_fingerprint", json={
            "bc_id": bc_id,
        })
        return resp.json()["strdata"]

    def captcha_encrypt(self, data, key, nonce):
        resp = http_requests.post(f"{self.base_url}/captcha/encrypt", json={
            "data": data,
            "key": key,
            "nonce": nonce,
        })
        return resp.json()["edata"]

logger = structlog.get_logger()

VERIFICATION_DOMAINS = {
    "sg": "verification-sg.tiktok.com",
    "va": "verification-va.tiktok.com",
    "us": "verification-us.tiktok.com",
    "eu": "verification.tiktokw.eu"
}


INDUSTRY_IDS = [10001010,10001110,10001210,10001410,10011010,10011210,10011410,10021014,10031012,10031117,10041011,10041123,10051010,10051110,10051210,10061016,10061114,10071015,10071113,10071212,10071312,10081014,10081112,10081230,10081313,10091024,10091122,10101016,10101117,10101210,10101317,10111017,10111120,10121015,10121110,10121210,10121310,10121411,10131012,10131111,10131214,10141016,10141128,10141225,10141314,10151010,10151116,10161013,10171020,10171113,10171210,10171310,10181010,10181112,10181210,10181310,10181410,10181510,10191017,10191114,10201013,10201122,10201232,10201310,10211013,10211111,1021101010,1021101126,1021101213,1021101310,1021111010,1021111110,1022101027,1022101121,1022101218,1022101322,1022101419,1022101528,1022101630,1022101713,1022101815,1022101920,1022102020,1022102112,1022102222,1022102324,1022111011,1022111111,1022111210]


class TiktokAdsGen:
    def __init__(self, proxy: str = None, card: dict = None, signer_url: str = "http://108.165.237.13:8004"):
        self.user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'
        self.session = curl_requests.Session(impersonate="chrome136")
        self.signer = SignerClient(signer_url)
        self.signer_url = signer_url
        self.canvas_fingerprint = random.randint(1111111111, 9999999999)
        self.region = None
        self.mssdk_domain = None
        self.verification_domain = None
        self.card = card
        self.tz = "America/New_York"
        self.country = "US"
        self.currency = "USD"

        if proxy:
            self.session.proxies.update({"all": proxy})

    @staticmethod
    def encode_mobile(text):
        return ''.join(f'{ord(c) ^ 5:02x}' for c in text)

    def report_telemetry(self, region):
        payload = {
            "magic": 538969122,
            "version": 1,
            "dataType": 8,
            "strData": self.signer.telemetry_strdata(),
            "tspFromClient": int(time.time() * 1000)
        }

        timestamp = int(time.time())
        url = f'https://{region}/web/report?msToken='

        x_bogus = self.signer.xbogus(
            'msToken=',
            payload,
            self.user_agent,
            timestamp,
            self.canvas_fingerprint,
            1,
            14
        )

        signed_url = f"{url}&X-Bogus={x_bogus}"
        self.session.post(signed_url, json=payload)

    def get_session(self):
        params = {
            '_source_': 'ads_bc',
            'register_type': '1',
            'redirect': 'https://business.tiktok.com/select/?source=BC_home&attr_source=BC_home&redirect_from=login',
            'cacheSDK': 'false',
        }

        response = self.session.get('https://ads.tiktok.com/i18n/signup/', params=params)

        env_match = re.search(r'<script id="tiktok-environment"[^>]*>(.*?)</script>', response.text, re.DOTALL)
        if env_match:
            env_data = json.loads(env_match.group(1))
            self.mssdk_domain = env_data.get('mssdk', {}).get('reportDomain', 'mssdk-sg.tiktok.com')
            self.region = env_data.get('region', 'sg')
        else:
            self.mssdk_domain = 'mssdk-sg.tiktok.com'
            self.region = 'sg'

        region_key = self.region.lower().replace('ali', '')
        self.verification_domain = VERIFICATION_DOMAINS.get(region_key, "verification-sg.tiktok.com")

        timestamp = int(time.time())
        x_bogus = self.signer.xbogus('msToken=', None, self.user_agent, timestamp, self.canvas_fingerprint, 1, 14)
        self.session.get(f'https://ads.tiktok.com/api/v2/i18n/perf/tool/timezone/?msToken=&X-Bogus={x_bogus}')

        mstoken = self.session.cookies.get("msToken", "", domain=".tiktok.com")

        timestamp = int(time.time())
        x_bogus = self.signer.xbogus(f'aid=1583&token=tiktok_ads&ab_sdk_version=&msToken={mstoken}', None, self.user_agent, timestamp, self.canvas_fingerprint, 1, 14)
        self.session.get(f'https://ads.tiktok.com/api/v3/i18n/abtest/get_ab_version_by_trace_sid/?aid=1583&token=tiktok_ads&ab_sdk_version=&msToken={mstoken}&X-Bogus={x_bogus}')

        timestamp = int(time.time())
        x_bogus = self.signer.xbogus(f'msToken={mstoken}', None, self.user_agent, timestamp, self.canvas_fingerprint, 1, 14)
        signature = self.signer.signature(f'https://ads.tiktok.com/api/attrib/trace/init/?msToken={mstoken}&X-Bogus={x_bogus}', self.user_agent)
        self.session.post(f'https://ads.tiktok.com/api/attrib/trace/init/?msToken={mstoken}&X-Bogus={x_bogus}&_signature={signature}', json={})

        try:
            self.report_telemetry(self.mssdk_domain)
        except Exception as e:
            logger.warning("telemetry_failed", error=str(e))

    def send_email_activate_code(self, email):
        chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()'
        password = ''.join(random.choice(chars) for _ in range(15))

        encoded_email = self.encode_mobile(email)
        encoded_password = self.encode_mobile(password)

        mstoken = self.session.cookies.get("msToken", "", domain=".tiktok.com")
        verify_fp = self.signer.verify()

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://ads.tiktok.com',
            'referer': 'https://ads.tiktok.com/',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': self.user_agent,
            'x-requested-with': 'XMLHttpRequest',
        }

        data = {
            'mix_mode': '1',
            'aid': '1583',
            'service': 'https://ads.tiktok.com/i18n/signup/?_source_=ads_bc&register_type=1&redirect=https%3A%2F%2Fbusiness.tiktok.com%2Fselect%2F%3Fsource%3DBC_home%26attr_source%3DBC_home%26redirect_from%3Dlogin&cacheSDK=false',
            'language': 'en',
            'email': encoded_email,
            'password': encoded_password,
            'shark_extra': '{"country":"BE","account_type":2}',
            'fp': verify_fp,
            'verifyFp': verify_fp,
            'ect_type': '1',
            'email_logic_type': '1',
        }

        timestamp = int(time.time())
        url = f'https://business-sso.tiktok.com/send_email_activate_code/v2/?msToken={mstoken}'

        x_bogus = self.signer.xbogus(
            f'msToken={mstoken}',
            data,
            self.user_agent,
            timestamp,
            self.canvas_fingerprint,
            1,
            0
        )

        url_with_bogus = f"{url}&X-Bogus={x_bogus}"
        signature = self.signer.signature(url_with_bogus, self.user_agent)
        signed_url = f"{url_with_bogus}&_signature={signature}"

        encoded_data = urlencode(data)
        response = self.session.post(signed_url, headers=headers, data=encoded_data)

        if response.status_code == 200 and response.json().get('error_code') == 1107:
            verify_conf_str = response.json().get('verify_center_decision_conf', '{}')
            verify_conf = json.loads(verify_conf_str)

            new_verify_fp = verify_conf.get('fp')
            server_sdk_env_data = json.loads(verify_conf.get('server_sdk_env', '{}'))
            region = server_sdk_env_data.get('region', 'sg').lower()
            detail = verify_conf.get('detail', '')
            server_sdk_env = verify_conf.get('server_sdk_env', '')

            captcha_domain = f"https://{self.verification_domain}"
            device_id = "0"

            params = {
                'lang': 'en',
                'app_name': 'adweb',
                'h5_sdk_version': '2.34.12',
                'h5_sdk_use_type': 'goofy',
                'sdk_version': '',
                'iid': '0',
                'did': device_id,
                'device_id': device_id,
                'ch': 'web_text',
                'aid': '1583',
                'os_type': '2',
                'mode': '3d',
                'tmp': str(int(time.time() * 1000)),
                'platform': 'pc',
                'webdriver': 'false',
                'enable_image': '1',
                'fp': new_verify_fp,
                'type': 'verify',
                'detail': detail,
                'server_sdk_env': quote_plus(server_sdk_env),
                'subtype': '3d',
                'challenge_code': '99997',
                'os_name': 'other',
                'region': region,
                'msToken': mstoken,
            }

            captcha_url = f'{captcha_domain}/captcha/get?' + '&'.join([f"{k}={v}" for k, v in params.items()])

            timestamp = int(time.time())
            x_bogus = self.signer.xbogus(
                '&'.join([f"{k}={v}" for k, v in params.items()]),
                None,
                self.user_agent,
                timestamp,
                self.canvas_fingerprint,
                1,
                14
            )

            signed_captcha_url = f"{captcha_url}&X-Bogus={x_bogus}"
            captcha_response = self.session.get(signed_captcha_url)

            if captcha_response.status_code == 200:
                captcha_json = captcha_response.json()
                if 'edata' in captcha_json:
                    decrypted_obj, key, nonce = self.signer.captcha_decrypt(captcha_json['edata'])
                    challenge = decrypted_obj['data']['challenges'][0]
                    verify_id = decrypted_obj['data']['verify_id']

                    solution = solve_3d_captcha(self.session, challenge, decrypted_obj)
                    encrypted_solution = self.signer.captcha_encrypt(solution, key, nonce)

                    verify_params = {
                        'lang': 'en',
                        'app_name': 'adweb',
                        'h5_sdk_version': '2.34.12',
                        'h5_sdk_use_type': 'goofy',
                        'sdk_version': '',
                        'iid': '0',
                        'did': device_id,
                        'device_id': device_id,
                        'ch': 'web_text',
                        'aid': '1583',
                        'os_type': '2',
                        'mode': '3d',
                        'tmp': str(int(time.time() * 1000)),
                        'platform': 'pc',
                        'webdriver': 'false',
                        'enable_image': '1',
                        'fp': new_verify_fp,
                        'type': 'verify',
                        'detail': detail,
                        'server_sdk_env': quote_plus(server_sdk_env),
                        'imagex_domain': '',
                        'subtype': '3d',
                        'challenge_code': '99997',
                        'os_name': 'other',
                        'verify_id': verify_id,
                        'h5_check_version': '3.8.20',
                        'region': region,
                        'triggered_region': region,
                        'cookie_enabled': 'true',
                        'screen_width': '1920',
                        'screen_height': '1080',
                        'browser_language': 'en-US',
                        'browser_platform': 'Linux x86_64',
                        'browser_name': 'Mozilla',
                        'browser_version': quote_plus(self.user_agent),
                        'msToken': mstoken,
                    }

                    verify_url = f'{captcha_domain}/captcha/verify?' + '&'.join([f"{k}={v}" for k, v in verify_params.items()])

                    verify_timestamp = int(time.time())
                    verify_x_bogus = self.signer.xbogus(
                        '&'.join([f"{k}={v}" for k, v in verify_params.items()]),
                        None,
                        self.user_agent,
                        verify_timestamp,
                        self.canvas_fingerprint,
                        1,
                        14
                    )

                    verify_url_with_bogus = f"{verify_url}&X-Bogus={verify_x_bogus}"
                    verify_signature = self.signer.signature(verify_url_with_bogus, self.user_agent)
                    verify_signed_url = f"{verify_url_with_bogus}&_signature={verify_signature}"

                    verify_response = self.session.post(
                        verify_signed_url,
                        headers={'content-type': 'application/json;charset=UTF-8'},
                        json={'edata': encrypted_solution}
                    )

                    if 'edata' in verify_response.json():
                        verify_result, _, _ = self.signer.captcha_decrypt(verify_response.json()['edata'])
                        logger.info("captcha", result=verify_result.get('code'))

                        if verify_result.get('code') == 200:
                            data['fp'] = new_verify_fp
                            data['verifyFp'] = new_verify_fp

                            retry_timestamp = int(time.time())
                            retry_url = f'https://business-sso.tiktok.com/send_email_activate_code/v2/?msToken={mstoken}'

                            retry_x_bogus = self.signer.xbogus(
                                f'msToken={mstoken}',
                                data,
                                self.user_agent,
                                retry_timestamp,
                                self.canvas_fingerprint,
                                1,
                                0
                            )

                            retry_url_with_bogus = f"{retry_url}&X-Bogus={retry_x_bogus}"
                            retry_signature = self.signer.signature(retry_url_with_bogus, self.user_agent)
                            retry_signed_url = f"{retry_url_with_bogus}&_signature={retry_signature}"

                            retry_encoded_data = urlencode(data)
                            response = self.session.post(retry_signed_url, headers=headers, data=retry_encoded_data)
                            verify_fp = new_verify_fp
                        else:
                            logger.error("captcha_failed", code=verify_result.get('code'), msg=verify_result.get('message'))

        resp_json = response.json()
        error_code = resp_json.get('error_code')
        if error_code == 0:
            status = "success"
        elif error_code == 1107:
            status = "captcha_failed"
        else:
            status = "failed"

        return response, password, verify_fp, status

    def activate_email(self, email, password, otp_code, verify_fp):
        encoded_email = self.encode_mobile(email)
        encoded_password = self.encode_mobile(password)
        encoded_code = self.encode_mobile(otp_code)
        mstoken = self.session.cookies.get("msToken", "", domain=".tiktok.com")

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'no-cache',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://ads.tiktok.com',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': 'https://ads.tiktok.com/',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': self.user_agent,
            'x-requested-with': 'XMLHttpRequest',
        }

        data = {
            'mix_mode': '1',
            'aid': '1583',
            'service': 'https://business.tiktok.com/select/?source=BC_home&attr_source=BC_home&redirect_from=login',
            'language': 'en',
            'email': encoded_email,
            'password': encoded_password,
            'code': encoded_code,
            'shark_extra': '{"country":"BE","account_type":2}',
            'force_bind_mobile': '0',
            'user_register_channel': '',
            'fp': verify_fp,
            'verifyFp': verify_fp,
            'ect_type': '1',
            'email_logic_type': '1',
        }

        timestamp = int(time.time())
        url = f'https://business-sso.tiktok.com/activate_email/register/?msToken={mstoken}'

        x_bogus = self.signer.xbogus(
            f'msToken={mstoken}',
            data,
            self.user_agent,
            timestamp,
            self.canvas_fingerprint,
            1,
            0
        )

        url_with_bogus = f"{url}&X-Bogus={x_bogus}"
        signature = self.signer.signature(url_with_bogus, self.user_agent)
        signed_url = f"{url_with_bogus}&_signature={signature}"

        encoded_data = urlencode(data)
        response = self.session.post(signed_url, headers=headers, data=encoded_data)

        return response

    def sso_callback(self, redirect_url):
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        ticket = params.get('ticket', [''])[0]
        next_url = params.get('next', [''])[0]

        mstoken = self.session.cookies.get("msToken", "", domain=".tiktok.com")

        callback_params = f'next={quote_plus(next_url)}&ticket={ticket}&msToken={mstoken}'

        timestamp = int(time.time())
        x_bogus = self.signer.xbogus(
            callback_params,
            None,
            self.user_agent,
            timestamp,
            self.canvas_fingerprint,
            1,
            14
        )

        callback_url = f'https://business.tiktok.com/passport/sso/login/callback/?{callback_params}&X-Bogus={x_bogus}'
        signature = self.signer.signature(callback_url, self.user_agent)
        signed_url = f'{callback_url}&_signature={signature}'

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://ads.tiktok.com',
            'referer': 'https://ads.tiktok.com/',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': self.user_agent,
            'x-requested-with': 'XMLHttpRequest',
        }

        response = self.session.get(signed_url, headers=headers)
        return response

    def get_account_info(self):
        passport_csrf = self.session.cookies.get("passport_csrf_token", "", domain=".tiktok.com")

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/x-www-form-urlencoded',
            'referer': 'https://business.tiktok.com/account/create?source=TTBC_HOME',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-tt-passport-csrf-token': passport_csrf,
        }

        url = f'https://business.tiktok.com/passport/web/account/info/?language=en&aid=2239&mix_mode=1&fixed_mix_mode=1'
        response = self.session.get(url, headers=headers)
        return response.json()

    def get_csrf_token(self):
        resp = self.session.get('https://business.tiktok.com/api/bff/v3/bm/setting/csrf-token')
        data = resp.json()
        if data.get('code') == 0:
            return data.get('data', {}).get('csrfToken', '')
        return ''

    def setup_business(self):
        mstoken = self.session.cookies.get("msToken", "", domain=".tiktok.com")

        timestamp = int(time.time())
        params = f'msToken={mstoken}'
        x_bogus = self.signer.xbogus(params, None, self.user_agent, timestamp, self.canvas_fingerprint, 1, 14)
        url = f'https://ads.tiktok.com/api/v1/business_setup/market_opt/wa_status/?{params}&X-Bogus={x_bogus}'
        signature = self.signer.signature(url, self.user_agent)
        self.session.get(f'{url}&_signature={signature}')

        timestamp = int(time.time())
        params = f'source=&event=signup&msToken={mstoken}'
        x_bogus = self.signer.xbogus(params, None, self.user_agent, timestamp, self.canvas_fingerprint, 1, 14)
        url = f'https://ads.tiktok.com/api/v2/bm/user/trace/?{params}&X-Bogus={x_bogus}'
        signature = self.signer.signature(url, self.user_agent)
        self.session.get(f'{url}&_signature={signature}')

    def create_business_center(self, company_name: str, email: str, phone: str):
        self.setup_business()
        self.session.get('https://business.tiktok.com/account/create?source=TTBC_HOME')

        mstoken = self.session.cookies.get("msToken", "", domain=".tiktok.com")
        passport_csrf = self.session.cookies.get("passport_csrf_token", "", domain=".tiktok.com")
        tta_attr_id = self.session.cookies.get("tta_attr_id_mirror", "", domain=".tiktok.com")
        csrftoken = self.get_csrf_token()

        account_info = self.get_account_info()
        user_id = account_info.get('data', {}).get('user_id_str', '')

        if not tta_attr_id:
            tta_attr_id = f"0.{int(time.time())}.{user_id}"

        industry_id = random.choice(INDUSTRY_IDS)

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://business.tiktok.com',
            'referer': 'https://business.tiktok.com/account/create?source=TTBC_HOME',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-csrftoken': csrftoken,
            'x-tt-passport-csrf-token': passport_csrf,
        }

        data = {
            "scene": 1,
            "req_source": 1,
            "self_serve": True,
            "record_type": 1,
            "is_decoupled": False,
            "company_info": {
                "need_create": True,
                "company_name": company_name,
                "industry_info_v4": {
                    "industry_id": industry_id,
                    "industry_id_level": 3
                },
                "country": self.country
            },
            "contact_info": {
                "contact_name": company_name,
                "contact_email": email,
                "contact_phone_number": phone,
                "contact_phone_country": self.country,
                "email_source": 2,
                "number_source": 0
            },
            "business_center_info": {
                "need_create": True,
                "business_center_name": company_name,
                "timezone": self.tz,
                "payment_currency": self.currency,
                "business_center_type": 5
            },
            "qualification_info": {
                "website": company_name
            },
            "account_info": {
                "need_create": True,
                "account_type": 1,
                "account_name": company_name,
                "account_time_zone": self.tz,
                "account_biz_type": 2,
                "btp_checked": False
            },
            "billing_info": {
                "sign_contract": False
            },
            "attribution_info": {
                "attr_source": "business-center",
                "page_url_base": "https://business.tiktok.com",
                "page_url_query": {
                    "source": "TTBC_HOME",
                    "attr_source": "business-center",
                    "attr_medium": "bc-self-serve"
                },
                "uv_data": {
                    "submission_page_url": "https://business.tiktok.com/account/create?source=TTBC_HOME",
                    "trace_sid": tta_attr_id,
                    "core_user_id": user_id
                }
            },
            "risk_info": {
                "cookie_enabled": True,
                "screen_width": 1920,
                "screen_height": 1080,
                "browser_language": "en-US",
                "browser_platform": "Linux x86_64",
                "browser_name": "Netscape",
                "browser_version": "5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                "browser_online": True,
                "timezone_name": self.tz,
                "mobile": False,
                "user_agent": self.user_agent,
                "language": "en"
            }
        }

        timestamp = int(time.time())
        url = f'https://business.tiktok.com/api/v3/bm/bp/create/?msToken={mstoken}'

        x_bogus = self.signer.xbogus(
            f'msToken={mstoken}',
            data,
            self.user_agent,
            timestamp,
            self.canvas_fingerprint,
            1,
            14
        )

        url_with_bogus = f"{url}&X-Bogus={x_bogus}"
        signature = self.signer.signature(url_with_bogus, self.user_agent)
        signed_url = f"{url_with_bogus}&_signature={signature}"

        response = self.session.post(signed_url, headers=headers, json=data)
        return response.json()

    def get_bm_user(self):
        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
        }

        response = self.session.get('https://business.tiktok.com/api/v2/bm/user/', headers=headers)
        return response.json()

    def update_user_finance_role(self, bc_id: str, user_id: str):
        csrftoken = self.session.cookies.get("csrftoken", "", domain="business.tiktok.com")
        mstoken = self.session.cookies.get("msToken", "", domain="business.tiktok.com")

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://business.tiktok.com',
            'referer': f'https://business.tiktok.com/manage/financeRole?org_id={bc_id}',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-csrftoken': csrftoken,
        }

        data = {
            "user_id": user_id,
            "role": 1,
            "user_name": "",
            "finance_role": 5,
            "risk_info": {
                "cookie_enabled": True,
                "screen_width": 1920,
                "screen_height": 1080,
                "browser_language": "en-US",
                "browser_platform": "Linux x86_64",
                "browser_name": "Mozilla",
                "browser_version": self.user_agent,
                "browser_online": True,
                "timezone_name": self.tz,
                "permission_source": "bc"
            }
        }

        timestamp = int(time.time())
        params = f'org_id={bc_id}&attr_source=&source_biz_id=&attr_type=web&msToken={mstoken}'
        x_bogus = self.signer.xbogus(params, data, self.user_agent, timestamp, self.canvas_fingerprint, 1, 14)
        url = f'https://business.tiktok.com/api/v2/bm/admin/user/update/?{params}&X-Bogus={x_bogus}'
        signature = self.signer.signature(url, self.user_agent)
        signed_url = f'{url}&_signature={signature}'

        response = self.session.post(signed_url, headers=headers, json=data)
        return response.json()

    def get_us_toponym(self):
        csrftoken = self.session.cookies.get("csrftoken", "", domain="business.tiktok.com")

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-csrftoken': csrftoken,
        }

        response = self.session.get('https://business.tiktok.com/api/v2/i18n/toponym/?country_code=US&language=en', headers=headers)
        return response.json()

    def get_geography(self, geoid: str):
        csrftoken = self.session.cookies.get("csrftoken", "", domain="business.tiktok.com")

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-csrftoken': csrftoken,
        }

        response = self.session.get(f'https://business.tiktok.com/api/v1/self-serve/geography/?geoid={geoid}&language=en', headers=headers)
        return response.json()

    def setup_billing(self, bc_id: str, address: str, state: str, county: str, city: str, post_code: str):
        csrftoken = self.session.cookies.get("csrftoken", "", domain="business.tiktok.com")
        mstoken = self.session.cookies.get("msToken", "", domain="business.tiktok.com")

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://business.tiktok.com',
            'referer': f'https://business.tiktok.com/manage/add-billing-info?org_id={bc_id}',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-csrftoken': csrftoken,
        }

        data = {
            "address_detail": address,
            "state": state,
            "county": county,
            "city": city,
            "post_code": post_code,
            "payment": 1,
            "tax_type": 3,
            "tax_map": {},
            "risk_info": {
                "cookie_enabled": True,
                "screen_width": 1920,
                "screen_height": 1080,
                "browser_language": "en-US",
                "browser_platform": "Linux x86_64",
                "browser_name": "Mozilla",
                "browser_version": self.user_agent,
                "browser_online": True,
                "timezone_name": self.tz,
                "permission_source": "bc"
            }
        }

        timestamp = int(time.time())
        params = f'org_id={bc_id}&attr_source=&source_biz_id=&attr_type=web&msToken={mstoken}'
        x_bogus = self.signer.xbogus(params, data, self.user_agent, timestamp, self.canvas_fingerprint, 1, 14)
        url = f'https://business.tiktok.com/api/v2/bm/organization/qualified/billing/?{params}&X-Bogus={x_bogus}'
        signature = self.signer.signature(url, self.user_agent)
        signed_url = f'{url}&_signature={signature}'

        response = self.session.post(signed_url, headers=headers, json=data)
        return response.json()

    def generate_random_address(self):
        states = self.get_us_toponym()
        if states.get('code') != 0:
            return None

        state = random.choice(states['data']['data'])
        state_geoid = str(state['geoid'])
        state_name = state['toponym_name']

        counties = self.get_geography(state_geoid)
        if counties.get('code') != 0 or not counties['data']['data']:
            return None

        county = random.choice(counties['data']['data'])
        county_geoid = str(county['geoid'])

        cities = self.get_geography(county_geoid)
        if cities.get('code') != 0 or not cities['data']['data']:
            return None

        city = random.choice(cities['data']['data'])
        city_geoid = str(city['geoid'])
        city_name = city.get('name') or city.get('name_en') or city.get('display_name') or 'Los Angeles'

        street_num = random.randint(100, 9999)
        street_names = ["Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine Rd", "Elm St", "Park Ave", "Lake Dr", "Hill Rd", "River St"]
        address = f"{street_num} {random.choice(street_names)}"
        post_code = str(random.randint(10000, 99999))

        return {
            "address": address,
            "state": state_geoid,
            "county": county_geoid,
            "city": city_geoid,
            "post_code": post_code,
            "state_name": state_name,
            "city_name": city_name
        }

    def query_payment_account(self, bc_id: str):
        csrftoken = self.session.cookies.get("csrftoken", "", domain="business.tiktok.com")
        passport_csrf = self.session.cookies.get("passport_csrf_token", "", domain="business.tiktok.com")

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://business.tiktok.com',
            'referer': f'https://business.tiktok.com/manage/payment/v2?org_id={bc_id}',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-csrftoken': csrftoken,
            'x-tt-passport-csrf-token': passport_csrf,
        }

        data = {
            "Context": {
                "platform": 2,
                "adv_id": "",
                "bc_id": bc_id
            },
            "module_list": [0, 3]
        }

        url = f'https://business.tiktok.com/pa/api/spider/query_payment_account/?org_id={bc_id}&attr_source=&source_biz_id=&attr_type=web'
        response = self.session.post(url, headers=headers, json=data)
        return response.json()

    def query_pay_url(self, bc_id: str, pa_id: str, amount: str = "10"):
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en',
            'content-type': 'application/json',
            'origin': 'https://business.tiktok.com',
            'referer': f'https://business.tiktok.com/manage/payment/v2?org_id={bc_id}',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-requested-with': 'XMLHttpRequest',
        }

        data = {
            "terminal_equip_name": "SDK",
            "entry_point": "BC_PAYMENT",
            "account_source": 1,
            "upay_biz_id": "87316307533",
            "scene": "0",
            "after_tax_amount": amount,
            "before_tax_amount": amount,
            "currency": "USD",
            "Context": {
                "platform": 2,
                "pa_id": pa_id,
                "bc_id": bc_id
            }
        }

        url = 'https://business.tiktok.com/pa/api/common/query/payment/query_pay_url'
        response = self.session.post(url, headers=headers, json=data)
        return response.json()

    def get_pre_order(self, token: str):
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
        }

        url = f'https://business.tiktok.com/upay/i18n/payment/pre_order?token={quote_plus(token)}'
        response = self.session.get(url, headers=headers)
        return response.json()

    def get_payment_list(self, token: str):
        mstoken = self.session.cookies.get("msToken", "", domain="business.tiktok.com")

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
        }

        data = {"token": token}
        url = f'https://business.tiktok.com/upay/i18n/pi/payment/list?msToken={mstoken}'
        response = self.session.post(url, headers=headers, json=data)
        return response.json()

    def report_payment_telemetry(self, bc_id: str):
        payload = {
            "magic": 538969122,
            "version": 1,
            "dataType": 8,
            "strData": self.signer.payment_fingerprint(bc_id),
            "tspFromClient": int(time.time() * 1000)
        }

        timestamp = int(time.time())
        url = f'https://{self.mssdk_domain}/web/report?msToken='

        x_bogus = self.signer.xbogus(
            'msToken=',
            payload,
            self.user_agent,
            timestamp,
            self.canvas_fingerprint,
            1,
            14
        )

        signed_url = f"{url}&X-Bogus={x_bogus}"
        self.session.post(signed_url, json=payload)

    def get_nonce(self, token: str, bc_id: str):
        mstoken = self.session.cookies.get("msToken", "", domain="business.tiktok.com")

        headers = {
            'accept': 'application/json',
            'accept-language': 'en',
            'content-type': 'application/json',
            'origin': 'https://business.tiktok.com',
            'referer': f'https://business.tiktok.com/manage/payment/v2?org_id={bc_id}',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-requested-with': 'XMLHttpRequest',
            'x-upay-terminal': 'SDK',
            'x-upay-version': '1.0.1.1840',
        }

        risk_info = {
            "uid": "",
            "aid": "2239",
            "app_id": "2239",
            "app_name": "",
            "did": "0",
            "device_platform": "web",
            "session_aid": "2239",
            "priority_region": "US",
            "user_agent": self.user_agent,
            "referer": f"https://business.tiktok.com/manage/add-billing-info?org_id={bc_id}",
            "cookie_enabled": True,
            "screen_width": 1920,
            "screen_height": 1080,
            "browser_language": "en-US",
            "browser_platform": "Linux x86_64",
            "browser_name": "Mozilla",
            "browser_version": self.user_agent.replace("Mozilla/", ""),
            "browser_online": True,
            "timezone_name": self.tz,
            "device_fingerprint_id": ""
        }

        data = {
            "token": token,
            "riskInfo": json.dumps(risk_info, separators=(',', ':')),
            "paymentPage": False
        }

        timestamp = int(time.time())
        params = f'msToken={mstoken}'

        x_bogus = self.signer.xbogus(
            params,
            data,
            self.user_agent,
            timestamp,
            self.canvas_fingerprint,
            1,
            14
        )

        url = f'https://business.tiktok.com/upay/i18n/parameter/get_unified_bin_detail?{params}&X-Bogus={x_bogus}'
        signature = self.signer.signature(url, self.user_agent)
        signed_url = f'{url}&_signature={signature}'

        body = json.dumps(data, separators=(',', ':'))
        response = self.session.post(signed_url, headers=headers, data=body)
        return response.json()

    def get_pipopay_cert(self, nonce: str, pa_id: str):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        from cryptography import x509
        from cryptography.x509.oid import NameOID

        private_key = Ed25519PrivateKey.generate()

        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, f"11202511SHv232_sep_{pa_id}"),
        ])).sign(private_key, None)

        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        headers = {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/json',
            'origin': 'https://business.tiktok.com',
            'user-agent': self.user_agent,
        }

        data = {
            "csr": csr_pem,
            "muid": pa_id,
            "merchant_id": "11202511SHv232",
            "nonce": nonce
        }

        response = self.session.post('https://fp-sg.pipopay.com/payment/v1/cert', headers=headers, json=data)
        result = response.json()

        return {
            "cert": result.get("cert"),
            "private_key": private_key
        }

    def get_encrypted_data(self, nonce: str, pa_id: str):
        from datetime import datetime, timezone

        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://fp-sg.pipopay.com',
            'Referer': 'https://fp-sg.pipopay.com/obj/pipo-checkout-sg/pipo/fe/monetization/monetization_iframe/0047/iframe.html?merchant_id=11202511SHv232',
            'User-Agent': self.user_agent,
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Storage-Access': 'active',
        }

        biz_content = {
            "nonce": nonce,
            "merchant_id": "11202511SHv232",
            "merchant_user_id": pa_id,
            "country": "US"
        }

        request_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        biz_content_json = json.dumps(biz_content, separators=(',', ':'))
        data = f"merchant_id=11202511SHv232&request_time={quote_plus(request_time)}&biz_content={quote_plus(biz_content_json)}"

        response = self.session.post('https://fp-sg.pipopay.com/payment/v1/get_encrypted_data', headers=headers, data=data)
        return response.json()

    def submit_pipopay(self, nonce: str, pa_id: str, charge_id: str, transaction_seq: str, amount: str, bc_id: str, payment_reference: str, risk_info: str, address_info: dict, cert_info: dict):
        from datetime import datetime, timezone

        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://fp-sg.pipopay.com',
            'Referer': f'https://fp-sg.pipopay.com/obj/pipo-checkout-sg/pipo/fe/monetization/monetization_iframe/0047/iframe.html?merchant_id=11202511SHv232',
            'User-Agent': self.user_agent,
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Storage-Access': 'active',
            'x-pipo-certificate': cert_info['cert'].replace('\n', '\\n'),
            'x-pipo-sign-mode': '1',
        }

        card = self.card
        card_brand = "visa" if card['number'].startswith('4') else "mastercard"
        method_id = f"pm_pi_ccdc_{card_brand}_c_d"

        exp_year_short = card['exp_year'][-2:] if len(card['exp_year']) == 4 else card['exp_year']
        holder_name = ''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 10)))

        unique_id = ''.join(random.choices('0123456789abcdef', k=8)) + '-' + \
                    ''.join(random.choices('0123456789abcdef', k=4)) + '-' + \
                    ''.join(random.choices('0123456789abcdef', k=4)) + '-' + \
                    ''.join(random.choices('0123456789abcdef', k=4)) + '-' + \
                    ''.join(random.choices('0123456789abcdef', k=12))

        return_url = f"https://business.tiktok.com/wpay/oversea/result?invokerID=upay_{unique_id}&from=payNext&uniqueId={unique_id}&checkoutJumpTime={int(time.time() * 1000)}"

        biz_content = {
            "trace_id": transaction_seq,
            "amount": amount,
            "charge_id": charge_id,
            "configuration": {
                "environment": "live",
                "locale": "en",
                "flow": "web",
                "three_ds_del_mid_page": "true",
                "use_biz_land_page": False
            },
            "currency": "USD",
            "is_agreement": False,
            "merchant_user_id": pa_id,
            "payment_method": {
                "method_id": method_id,
                "element_params": {
                    "country_code": "US",
                    "currency": "USD",
                    "amount_value": amount,
                    "sdk_type": "go",
                    "sdk_version": "10.0.0"
                },
                "payment_elements": [
                    {"param_name": "card_number", "element": "eg_ccdc_global_card_number", "param_value": card['number']},
                    {"param_name": "expiration_month", "element": "eg_ccdc_global_expiration_month", "param_value": card['exp_month']},
                    {"param_name": "expiration_year", "element": "eg_ccdc_global_expiration_year", "param_value": exp_year_short},
                    {"param_name": "cvv", "element": "eg_ccdc_global_cvv", "param_value": card['cvv']},
                    {"param_name": "holder_name", "element": "eg_ccdc_global_holder_name", "param_value": holder_name},
                    {"element": "eg_ccdc_global_phone_country_code", "param_name": "phone_country_code", "param_value": "1", "is_encrypted": False},
                    {"element": "eg_ccdc_global_billing_address_state", "param_name": "billing_state", "param_value": address_info['state_name'], "is_encrypted": False},
                    {"element": "eg_ccdc_global_billing_address_city", "param_name": "billing_city", "param_value": address_info['city_name'], "is_encrypted": False},
                    {"element": "eg_ccdc_global_billing_address_postal_code", "param_name": "billing_postal_code", "param_value": address_info['post_code'], "is_encrypted": False},
                    {"element": "eg_ccdc_global_billing_address_street", "param_name": "billing_street", "param_value": address_info['address'], "is_encrypted": False},
                    {"element": "eg_ccdc_global_billing_address_country_regin", "param_name": "billing_country_region", "param_value": "US", "is_encrypted": False}
                ]
            },
            "payment_reference": payment_reference,
            "return_url": return_url,
            "risk_info": risk_info,
            "store_payment_method": True,
            "nonce": nonce,
            "country_or_region": "US",
            "merchant_id": "11202511SHv232"
        }

        request_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        biz_content_json = json.dumps(biz_content, separators=(',', ':'))
        data = f"merchant_id=11202511SHv232&request_time={quote_plus(request_time)}&biz_content={quote_plus(biz_content_json)}"

        signature = cert_info['private_key'].sign(data.encode())
        headers['x-pipo-signature'] = signature.hex()

        response = self.session.post('https://fp-sg.pipopay.com/payment/v1/pay', headers=headers, data=data)
        return response.json()

    def submit_order(self, token: str, charge_id: str, bc_id: str):
        mstoken = self.session.cookies.get("msToken", "", domain="business.tiktok.com")

        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://business.tiktok.com',
            'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-upay-terminal': 'SDK',
            'x-upay-version': '1.0.1.1840',
            'x-requested-with': 'XMLHttpRequest',
        }

        card = self.card
        card_brand = "visa" if card['number'].startswith('4') else "mastercard"
        payment_method_id = f"pm_pi_ccdc_{card_brand}_c_d"

        risk_info = {
            "uid": "",
            "aid": "2239",
            "app_id": "2239",
            "app_name": "",
            "did": "0",
            "device_platform": "web",
            "session_aid": "2239",
            "priority_region": "US",
            "user_agent": self.user_agent,
            "referer": f"https://business.tiktok.com/manage/add-billing-info?org_id={bc_id}",
            "cookie_enabled": True,
            "screen_width": 1920,
            "screen_height": 1080,
            "browser_language": "en-US",
            "browser_platform": "Linux x86_64",
            "browser_name": "Mozilla",
            "browser_version": self.user_agent.replace("Mozilla/", ""),
            "browser_online": True,
            "timezone_name": self.tz,
            "device_fingerprint_id": ""
        }

        unique_id = ''.join(random.choices('0123456789abcdef', k=8)) + '-' + \
                    ''.join(random.choices('0123456789abcdef', k=4)) + '-' + \
                    ''.join(random.choices('0123456789abcdef', k=4)) + '-' + \
                    ''.join(random.choices('0123456789abcdef', k=4)) + '-' + \
                    ''.join(random.choices('0123456789abcdef', k=12))

        return_url = f"https://business.tiktok.com/wpay/oversea/result?invokerID=upay_{unique_id}&from=payNext&uniqueId={unique_id}&actionType=pay"

        data = {
            "token": token,
            "payWay": 0,
            "recordNo": charge_id,
            "returnUrl": return_url,
            "riskInfo": json.dumps(risk_info, separators=(',', ':')),
            "terminalEquip": 4,
            "supportAgreementPaymentAndBind": True,
            "saveActionByBackend": True,
            "channelParameter": json.dumps({
                "paymentMethodId": payment_method_id,
                "supportAgreementPaymentAndBind": True
            }, separators=(',', ':')),
            "bindAndPay": True
        }

        timestamp = int(time.time())
        params = f'msToken={mstoken}'
        x_bogus = self.signer.xbogus(params, data, self.user_agent, timestamp, self.canvas_fingerprint, 1, 14)
        url = f'https://business.tiktok.com/upay/i18n/payment/submit_order?{params}&X-Bogus={x_bogus}'
        signature = self.signer.signature(url, self.user_agent)
        signed_url = f'{url}&_signature={signature}'
        body = json.dumps(data, separators=(',', ':'))
        response = self.session.post(signed_url, headers=headers, data=body)
        return response.json()

    def process_payment(self, bc_id: str, pa_id: str, address_info: dict, amount: str = "10"):
        pay_url_result = self.query_pay_url(bc_id, pa_id, amount)
        if pay_url_result.get('code') != 0:
            return {"error": "query_pay_url failed", "details": pay_url_result}

        url_data = pay_url_result['data']
        transaction_seq = url_data['transaction_seq']

        parsed = urlparse(url_data['url'])
        params = parse_qs(parsed.query)
        token = params.get('token', [''])[0]

        pre_order = self.get_pre_order(token)
        if pre_order.get('code') != 0:
            return {"error": "pre_order failed", "details": pre_order}

        charge_id = pre_order['data']['charge_id']
        logger.info("pre_order", charge_id=charge_id)

        self.get_payment_list(token)

        try:
            self.report_payment_telemetry(bc_id)
        except Exception as e:
            logger.warning("payment_telemetry_failed", error=str(e))

        nonce_result = self.get_nonce(token, bc_id)
        if nonce_result.get('code') != 0:
            return {"error": "get_nonce failed", "details": nonce_result}
        logger.info("nonce_obtained")

        submit_result = self.submit_order(token, charge_id, bc_id)
        logger.info("submit_order", code=submit_result.get('code'))

        if submit_result.get('code') != 0:
            return {"error": "submit_order failed", "details": submit_result}

        payment_reference = submit_result['data']['paymentReference']
        risk_info = submit_result['data'].get('riskInfo', '{}')
        pipopay_nonce = submit_result['data']['nonce']
        logger.info("got_payment_reference", ref=payment_reference)

        cert_info = self.get_pipopay_cert(pipopay_nonce, pa_id)
        if not cert_info.get('cert'):
            return {"error": "get_cert failed", "details": cert_info}
        logger.info("got_cert")

        self.get_encrypted_data(pipopay_nonce, pa_id)
        logger.info("get_encrypted_data_done")

        pipopay_result = self.submit_pipopay(pipopay_nonce, pa_id, charge_id, transaction_seq, amount, bc_id, payment_reference, risk_info, address_info, cert_info)
        pipopay_response = json.loads(pipopay_result.get('response', '{}'))
        logger.info("pipopay_result", result_code=pipopay_response.get('result_code'), error=pipopay_response.get('error_code'), msg=pipopay_response.get('error_message'))

        return {
            "success": pipopay_response.get('result_code') == 'success',
            "transaction_seq": transaction_seq,
            "charge_id": charge_id,
            "pipopay_response": pipopay_response,
            "submit_result": submit_result
        }

    def export_session(self):
        cookies = []
        for cookie in self.session.cookies.jar:
            cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            })
        return {
            "cookies": cookies,
            "canvas_fingerprint": self.canvas_fingerprint,
            "mssdk_domain": self.mssdk_domain,
            "region": self.region,
            "verification_domain": self.verification_domain,
            "user_agent": self.user_agent,
            "tz": self.tz,
            "country": self.country,
            "currency": self.currency,
            "signer_url": self.signer_url,
        }

    @classmethod
    def from_session(cls, session_data, proxy=None, card=None):
        signer_url = session_data.get("signer_url", "http://108.165.237.13:8004")
        instance = cls(proxy=proxy, card=card, signer_url=signer_url)
        instance.canvas_fingerprint = session_data["canvas_fingerprint"]
        instance.mssdk_domain = session_data["mssdk_domain"]
        instance.region = session_data["region"]
        instance.verification_domain = session_data["verification_domain"]
        instance.user_agent = session_data["user_agent"]
        instance.tz = session_data.get("tz", "America/New_York")
        instance.country = session_data.get("country", "US")
        instance.currency = session_data.get("currency", "USD")
        for c in session_data["cookies"]:
            instance.session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        return instance


app = FastAPI()


class CreateAccountRequest(BaseModel):
    proxy: str
    zeus_key: str
    company_name: Optional[str] = None
    phone: Optional[str] = None
    country: str = "US"
    timezone: str = "America/New_York"
    currency: str = "USD"
    address_info: Optional[dict] = None
    signer_url: str = "http://108.165.237.13:8004"


class TopupRequest(BaseModel):
    card: dict
    amount: str = "10"
    session_data: dict
    bc_id: str
    pa_id: str
    address_info: dict
    proxy: str


@app.post("/createaccount")
def create_account(req: CreateAccountRequest):
    try:
        gen = TiktokAdsGen(proxy=req.proxy, signer_url=req.signer_url)
        gen.tz = req.timezone
        gen.country = req.country
        gen.currency = req.currency
        mail = ZeusXMail(api_key=req.zeus_key)

        gen.get_session()
        logger.info("session_ready", region=gen.region)

        email = mail.generate_email()
        if not email:
            return {"error": "email_gen_failed"}
        logger.info("email_generated", email=email)

        response, password, verify_fp, status = gen.send_email_activate_code(email)
        resp_json = response.json()
        logger.info("send_email_result", status=status, error_code=resp_json.get('error_code'), description=resp_json.get('description'))
        if status != "success":
            return {
                "error": f"email_send_{status}",
                "error_code": resp_json.get('error_code'),
                "description": resp_json.get('description'),
                "response": resp_json,
            }

        otp_code = mail.get_email_code(timeout=120)
        if not otp_code:
            return {"error": "otp_timeout"}
        logger.info("otp_received")

        activate_response = gen.activate_email(email, password, otp_code, verify_fp)
        activate_json = activate_response.json()
        logger.info("activate_result", error_code=activate_json.get('error_code'), description=activate_json.get('description'))
        if activate_json.get('error_code') != 0:
            return {
                "error": "activation_failed",
                "error_code": activate_json.get('error_code'),
                "description": activate_json.get('description'),
                "response": activate_json,
            }

        redirect_url = activate_response.json().get('redirect_url', '')
        if redirect_url:
            gen.sso_callback(redirect_url)
        logger.info("account_activated")

        company_name = req.company_name or (''.join(random.choices(string.ascii_lowercase, k=8)).capitalize() + " LLC")
        phone = req.phone or ("+1" + ''.join(random.choices(string.digits, k=10)))

        bc_result = gen.create_business_center(company_name, email, phone)
        logger.info("bc_result", code=bc_result.get('code'), msg=bc_result.get('msg'))
        if bc_result.get('code') != 0:
            return {"error": "bc_creation_failed", "response": bc_result}

        bc_id = bc_result['data']['org_id']
        adv_id = bc_result['data']['adv_id']
        logger.info("bc_created", bc_id=bc_id, adv_id=adv_id)

        user_info = gen.get_bm_user()
        logger.info("bm_user", code=user_info.get('code'))
        if user_info.get('code') != 0:
            return {"error": "user_info_failed", "response": user_info}

        user_id = user_info['data']['id']
        logger.info("user_id", user_id=user_id)

        finance_result = gen.update_user_finance_role(bc_id, user_id)
        logger.info("finance_role", code=finance_result.get('code'))
        if finance_result.get('code') != 0:
            return {"error": "finance_role_failed", "response": finance_result}

        if req.address_info:
            address_info = req.address_info
        else:
            address_info = gen.generate_random_address()
            if not address_info:
                return {"error": "address_generation_failed"}
        logger.info("address_generated", state=address_info.get('state_name'), city=address_info.get('city_name'))

        billing_result = gen.setup_billing(
            bc_id, address_info['address'], address_info['state'],
            address_info['county'], address_info['city'], address_info['post_code']
        )
        logger.info("billing_result", code=billing_result.get('code'))
        if billing_result.get('code') != 0:
            return {"error": "billing_setup_failed", "response": billing_result}

        gen.session.get(f'https://business.tiktok.com/manage/payment/v2?org_id={bc_id}')

        pa_id = None
        for attempt in range(5):
            time.sleep(2)
            payment_info = gen.query_payment_account(bc_id)
            if payment_info.get('code') == 0 and payment_info['data'].get('pa_info'):
                pa_id = payment_info['data']['pa_info']['pa_id']
                logger.info("payment_account", pa_id=pa_id)
                break
            logger.info("waiting_for_pa", attempt=attempt + 1, code=payment_info.get('code'))

        if not pa_id:
            return {"error": "payment_account_failed", "response": payment_info}

        session_data = gen.export_session()

        return {
            "email": email,
            "email_password": mail.password,
            "account_password": password,
            "bc_id": bc_id,
            "adv_id": adv_id,
            "user_id": user_id,
            "pa_id": pa_id,
            "address_info": address_info,
            "proxy": req.proxy,
            "session_data": session_data,
            "mail_data": {
                "api_key": mail.api_key,
                "client_id": mail.client_id,
                "refresh_token": mail.refresh_token,
                "access_token": mail.access_token,
            },
        }
    except Exception as e:
        logger.exception("createaccount_exception")
        return {"error": "exception", "exception": type(e).__name__, "message": str(e)}


@app.post("/topup")
def topup(req: TopupRequest):
    try:
        logger.info("topup_start", bc_id=req.bc_id, pa_id=req.pa_id, amount=req.amount)
        gen = TiktokAdsGen.from_session(
            session_data=req.session_data,
            proxy=req.proxy,
            card=req.card,
        )
        result = gen.process_payment(req.bc_id, req.pa_id, req.address_info, req.amount)
        logger.info("topup_result", success=result.get('success'), error=result.get('error'))
        return result
    except Exception as e:
        logger.exception("topup_exception")
        return {"error": "exception", "exception": type(e).__name__, "message": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
