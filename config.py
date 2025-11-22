import os
from dotenv import load_dotenv

load_dotenv()
API_ID = 24296666
API_HASH= "01be7c04cc26bcf1017f47feb01701e3"
# Настройки бота
BOT_TOKEN='7490486016:AAEfRlCup2K17kPE6-WAet5Jg7vOGDG14NQ'
# Список каналов для мониторинга
MONITORED_CHANNELS = [
    "CryptoGrad",
    "Serebrov",
    "CryptoFutures",
    "Light",
    "NesterovFamily",
    "privateclub"
]

# Настройки мониторинга
MONITORING_CONFIG = {
    'update_interval': 5,  # секунды
    'log_threshold': 1.0,  # минимальный % изменения для логирования
}
# URL для веб-приложения (HTTPS от ngrok)
WEB_APP_URL = "https://ktt49wtkz7.eu.loclx.io"