FROM python:3.11-slim

WORKDIR /app

# نصب پیش‌نیازهای سیستم
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# ایجاد دایرکتوری‌های داده و کش
RUN mkdir -p data cache_avatars static/uploads

EXPOSE 5000

CMD ["python", "run.py"]
