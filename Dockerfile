# Python 3.12.3-slim tabanlı bir image kullan
FROM python:3.12.3-slim

# Çalışma dizinini /server olarak ayarla
WORKDIR /server

# Gerekli sistem paketlerini yükle
RUN apt-get update && apt-get install -y \
    libcairo2 \
    libcairo2-dev \
    libgl1-mesa-dev \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt dosyasını Docker konteynerine kopyala
COPY requirements.txt .

# Gerekli Python paketlerini yükle
RUN pip install --no-cache-dir -r requirements.txt

# Uygulamanın geri kalan dosyalarını Docker konteynerine kopyala
COPY . .

# Uygulamanın çalışacağı portu belirt (Flask varsayılan olarak 5000 portunu kullanır)
EXPOSE 5000

# Uygulamayı çalıştır
CMD ["python", "server.py"]
