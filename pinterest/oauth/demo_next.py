import requests
import json
import sys

# ================================
#  DEMO SCRIPT FOR PINTEREST REVIEW
#  This script demonstrates:
#   1. OAuth code exchange
#   2. Real Pinterest API calls
#   3. JSON responses shown on screen
# ================================

CLIENT_ID = "1536748"
CLIENT_SECRET = "4f5cf249c032eb8f376aa40fe2a4ed1808fb011a"
REDIRECT_URI = "https://post.equalle.com/pinterest/oauth/pinterest"


def wait():
    input("\nPress ENTER to continue...\n")


print("\n==============================")
print("  STEP 1 — Paste OAuth Code")
print("==============================")
print(
    "After completing the login flow in your browser, copy the value of the\n"
    "'code' parameter from the redirect URL.\n"
    "Example:\n"
    "https://post.equalle.com/pinterest/oauth/pinterest?code=ABCDE12345\n"
)

oauth_code = input("Enter OAuth code here: ").strip()

if not oauth_code:
    print("ERROR: No code entered.")
    sys.exit(1)

wait()

# =====================================
# STEP 2 — Exchange Code for Access Token
# =====================================

print("\n==============================")
print("  STEP 2 — Exchanging Code for Access Token")
print("==============================")
print("Sending POST request to /v5/oauth/token ...\n")

token_body = {
    "grant_type": "authorization_code",
    "code": oauth_code,
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
}

token_response = requests.post(
    "https://api.pinterest.com/v5/oauth/token",
    json=token_body
)

print("----- Raw Response from Pinterest (Code Exchange) -----")
print(token_response.text)
print("-------------------------------------------------------")

if token_response.status_code != 200:
    print("\nERROR: Unable to exchange code. Cannot continue.")
    sys.exit(1)

access_token = token_response.json().get("access_token")

if not access_token:
    print("\nERROR: No access token returned.")
    sys.exit(1)

print("\nAccess Token successfully obtained.")
wait()


# =====================================
# STEP 3 — GET /v5/user_account
# =====================================

print("\n==============================")
print("  STEP 3 — Calling Pinterest API: GET /v5/user_account")
print("==============================")
print(
    "This step demonstrates a REAL authenticated API call to Pinterest.\n"
    "This endpoint returns basic data about the authorized user.\n"
)

headers = {"Authorization": f"Bearer {access_token}"}

user_resp = requests.get("https://api.pinterest.com/v5/user_account", headers=headers)

print("----- JSON Response (user_account) -----")
print(user_resp.text)
print("----------------------------------------")

wait()


# =====================================
# STEP 4 — GET /v5/boards
# =====================================

print("\n==============================")
print("  STEP 4 — Calling Pinterest API: GET /v5/boards")
print("==============================")
print(
    "This shows the list of boards belonging to the authenticated account.\n"
    "Demonstrates scopes: boards:read.\n"
)

boards_resp = requests.get("https://api.pinterest.com/v5/boards", headers=headers)

print("----- JSON Response (boards) -----")
print(boards_resp.text)
print("----------------------------------")

wait()


# =====================================
# STEP 5 — GET /v5/pins for FIRST BOARD
# =====================================

print("\n==============================")
print("  STEP 5 — Calling Pinterest API: GET /v5/pins")
print("==============================")

boards_json = boards_resp.json()

if "items" not in boards_json or len(boards_json["items"]) == 0:
    print("No boards found. Cannot demonstrate pins API.")
else:
    first_board_id = boards_json["items"][0]["id"]
    print(f"Using first board ID: {first_board_id}\n")

    pins_resp = requests.get(
        f"https://api.pinterest.com/v5/pins?board_id={first_board_id}",
        headers=headers
    )

    print("----- JSON Response (pins) -----")
    print(pins_resp.text)
    print("--------------------------------")

wait()


# =====================================
# FINISHED
# =====================================

print("\n==============================")
print("  STEP 6 — Demo Completed")
print("==============================")
print(
    "This concludes the full Pinterest OAuth + API demonstration:\n"
    "✔ OAuth login performed in browser\n"
    "✔ Code exchanged for access token\n"
    "✔ GET /user_account\n"
    "✔ GET /boards\n"
    "✔ GET /pins\n\n"
    "All required elements for API approval are now shown.\n"
)

print("End of demo.")
