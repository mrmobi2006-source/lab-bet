FROM python:3.11-slim-bookworm

WORKDIR /app

# تثبيت المتطلبات الأساسية فقط
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت Chromium + كل الـ dependencies تلقائياً
RUN playwright install chromium && playwright install-deps chromium

COPY bot.py .

CMD ["python", "bot.py"]
