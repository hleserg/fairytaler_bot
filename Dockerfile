FROM python:3.11-slim
WORKDIR /app
# Установить curl, unzip, ffmpeg (для tts), и yc CLI
RUN apt-get update \
    && apt-get install -y curl unzip ffmpeg \
    && curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash \
    && rm -rf /var/lib/apt/lists/*
# Добавить yc CLI в PATH
ENV PATH="/root/yandex-cloud/bin:${PATH}"
# Создать папку для конфигов yc
RUN mkdir -p /root/.config/yandex-cloud
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
