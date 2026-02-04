# Gunakan Python 3.11 yang stabil
FROM python:3.11-slim

# Set folder kerja di dalam container
WORKDIR /app

# Install dependencies sistem yang dibutuhkan untuk aiosqlite/apscheduler
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements dulu (biar build lebih cepat kalau ada cache)
COPY requirements.txt .

# Install library python
RUN pip install --no-cache-dir -r requirements.txt

# Copy semua file kodingan ke dalam container
COPY . .

# Jalankan botnya
CMD ["python", "main.py"]
