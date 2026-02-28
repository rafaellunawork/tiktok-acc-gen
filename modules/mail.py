import time
import requests
import structlog

logger = structlog.get_logger()


class ZeusXMail:
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.base_url = 'https://api.zeus-x.ru'
        self.client_id = None
        self.email = None
        self.password = None
        self.refresh_token = None
        self.access_token = None

    def _purchase_account(self):
        r = requests.get(f'{self.base_url}/purchase', params={
            'apikey': self.api_key,
            'accountcode': 'HOTMAIL_TRUSTED_GRAPH_API',
            'quantity': 1
        })
        data = r.json()
        if data.get('Code') == 0 and data.get('Data', {}).get('Accounts'):
            acc = data['Data']['Accounts'][0]
            self.email = acc['Email']
            self.password = acc['Password']
            self.refresh_token = acc['RefreshToken']
            self.client_id = acc['ClientId']
            return acc
        return None

    def _get_access_token(self) -> str:
        data = {
            'client_id': self.client_id,
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token
        }
        r = requests.post('https://login.live.com/oauth20_token.srf', data=data)
        return r.json().get('access_token')

    def generate_email(self):
        acc = self._purchase_account()
        if acc:
            self.access_token = self._get_access_token()
            return self.email
        return None

    def _outlook_get_emails(self, folder='inbox'):
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        url = f'https://outlook.office.com/api/v2.0/me/mailfolders/{folder}/messages?$top=20&$select=Id,Subject,Body,From'
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            return r.json().get('value', [])
        return []

    def get_email_code(self, timeout=60, poll_interval=5):
        start = time.time()
        seen_ids = set()

        while time.time() - start < timeout:
            for folder in ['inbox', 'junkemail']:
                emails = self._outlook_get_emails(folder)
                for msg in emails:
                    msg_id = msg.get('Id', '')
                    if msg_id in seen_ids:
                        continue

                    subject = msg.get('Subject', '')
                    sender = msg.get('From', {}).get('EmailAddress', {}).get('Address', '')
                    body = msg.get('Body', {}).get('Content', '')

                    if 'tiktok' in sender.lower() or 'tiktok' in subject.lower():
                        try:
                            code = body.split('color:rgba(42,77,143,1)')[1].split('>')[1].split('<')[0].strip()
                            if len(code) == 6 and code.isalnum():
                                logger.info("code_fetched", code=code)
                                return code
                        except:
                            pass

                    seen_ids.add(msg_id)

            time.sleep(poll_interval)
        return None
