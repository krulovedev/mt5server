FROM python:3.11-slim

WORKDIR /app

# ติดตั้ง dependencies ก่อน (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy โค้ด
COPY . .

# Render inject $PORT อัตโนมัติ (default 8000 สำหรับ local)
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
