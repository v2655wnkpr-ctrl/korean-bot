import os
import staypresent

# Предоставляем Render endpoint для проверки работоспособности
staypresent.web.json({"status": "ok"})

# Запускаем исходный bot.py как подпроцесс
staypresent.run(
    "bot.py",
    port=int(os.getenv("PORT", 8080)),
    restart_on_crash=True
)
