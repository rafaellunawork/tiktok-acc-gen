import requests
import sys
import json

BASE_URL = "http://127.0.0.1:8003"

CARD = {
    "number": "",
    "exp_month": "",
    "exp_year": "",
    "cvv": ""
}


ZEUS_KEY = "mykey"

ADDRESS_INFO = {
    "address": "4827 Oak Ave",
    "state": "6252001-5128638",
    "county": "",
    "city": "",
    "post_code": "10001",
    "state_name": "New York",
    "city_name": "New York"
}

COMPANY_NAME = "Testify LLC"
PHONE = "+12125559876"
COUNTRY = "US"
TIMEZONE = "America/New_York"
CURRENCY = "USD"
SIGNER_URL = "http://108.165.237.13:8004"


PROXY = "http://pkg-royal-country-us-session-test1:mypassword@standard.vital-proxies.com:8603"
AMOUNT = "10"


def main():
    print("Creating account...")
    create_payload = {
        "proxy": PROXY,
        "zeus_key": ZEUS_KEY,
        "company_name": COMPANY_NAME,
        "phone": PHONE,
        "country": COUNTRY,
        "timezone": TIMEZONE,
        "currency": CURRENCY,
        "address_info": ADDRESS_INFO,
        "signer_url": SIGNER_URL,
    }

    resp = requests.post(f"{BASE_URL}/createaccount", json=create_payload, timeout=300)
    account = resp.json()

    if "error" in account:
        print(f"Account creation failed: {json.dumps(account, indent=2)}")
        sys.exit(1)

    print(account)

    print(f"\nTopping up ${AMOUNT}...")
    resp = requests.post(f"{BASE_URL}/topup", json={
        "card": CARD,
        "amount": AMOUNT,
        "session_data": account["session_data"],
        "bc_id": account["bc_id"],
        "pa_id": account["pa_id"],
        "address_info": account["address_info"],
        "proxy": account["proxy"],
    }, timeout=120)
    result = resp.json()

    if result.get("success"):
        print(f"Payment successful! Transaction: {result.get('transaction_seq')}")
    else:
        print(f"Payment failed: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
