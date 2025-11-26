import requests

def wait(step_text):
    print("\n" + step_text)
    input("Press ENTER to continue...\n")

# ============================
# CONFIG (только тут меняешь токен!)
# ============================
ACCESS_TOKEN = "PASTE_YOUR_TOKEN_HERE"   # <-- ВСТАВЬ ТВОЙ pina_... токен

LOGIN_PAGE_URL = "https://post.equalle.com/pinterest/oauth/login.html"
REDIRECT_EXAMPLE = "https://post.equalle.com/pinterest/oauth/pinterest?code=EXAMPLE_CODE_HERE"

# ============================
# DEMO FLOW
# ============================

wait("STEP 1 — Открываем страницу логина\n" +
     f"Открой в браузере этот URL:\n{LOGIN_PAGE_URL}\n" +
     "На видео покажи, что страница открывается.")

wait("STEP 2 — Нажимаем кнопку 'Login with Pinterest'\n" +
     "На видео покажи, что открывается Pinterest окно авторизации.\n" +
     "Там нажимаешь 'Give Access'.")

wait("STEP 3 — Redirect с кодом\n" +
     f"На экране браузера появится URL вида:\n{REDIRECT_EXAMPLE}\n" +
     "Покажи, что появляется параметр '?code=' — это важно для Pinterest review.")

wait("STEP 4 — Демонстрация API интеграции\n" +
     "Теперь скрипт покажет реальный API вызов через Pinterest API v5.\n" +
     "Это то, что Pinterest требует увидеть.")

# ============================
# REAL API CALL — GET BOARDS
# ============================

print("\nЗапрашиваю список досок через Pinterest API...")

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

response = requests.get("https://api.pinterest.com/v5/boards", headers=headers)

print("\n----- Pinterest API Response (GET /v5/boards) -----")
print(response.text)
print("---------------------------------------------------")

wait("STEP 5 — Конец демо\n"
     "Покажи на видео, что API вернул ответ (даже если пустой или частичный).\n"
     "Это доказательство реальной интеграции.")

print("Demo finished. Everything required for Pinterest approval was shown.")
