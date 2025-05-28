# SVG Duplicate Finder API

Bu proje, SVG dosyalarında duplikat görüntüleri bulmak için geliştirilmiş bir backend API'dir. Büyük miktarda resim yüklendiğinde timeout sorunlarını çözmek için asenkron işleme yapısı kullanır.

## Timeout Sorunu ve Çözümler

### Problem
Çok fazla resim yüklendiğinde işlem uzun sürdüğü için request timeout oluyor.

### Çözümler

#### 1. Asenkron İşleme (Önerilen)
`async_server.py` kullanarak:
- Upload derhal tamamlanır ve job ID döner
- İşleme background'da devam eder
- Progress API ile takip edilir
- Timeout sorunu tamamen çözülür

#### 2. Production Deployment
Gunicorn ile doğru konfigürasyon:
- Worker timeout: 300 saniye
- Multiple workers/threads
- Connection pooling

## Kullanım

### Development
```bash
python async_server.py
```

### Production (Docker)
```bash
# Async server için
docker build -f Dockerfile.async -t svg-duplicate-finder .
docker run -p 5000:5000 svg-duplicate-finder
```

### Production (Direct)
```bash
python production.py
```

## API Endpoints

### 1. Upload Files (Async)
```
POST /upload
```
**Request:** Multipart form data ile SVG dosyaları

**Response:**
```json
{
  "isSuccess": true,
  "jobId": "uuid-here",
  "message": "Processing started for 10 files. Use /status/uuid to check progress."
}
```

### 2. Check Job Status
```
GET /status/{jobId}
```
**Response:**
```json
{
  "isSuccess": true,
  "job": {
    "id": "uuid-here",
    "status": "processing",
    "progress": {
      "processed": 45,
      "total": 100,
      "percentage": 45.0
    },
    "files_count": 10
  }
}
```

**Job Status Values:**
- `pending`: İş kuyruğunda bekliyor
- `processing`: İşleniyor
- `completed`: Tamamlandı
- `failed`: Hata ile sonuçlandı

### 3. Get Results
```
GET /result/{jobId}
```
**Response (Success):**
```json
{
  "isSuccess": true,
  "message": "Duplicate images found.",
  "data": [
    {
      "fileName": "image1.svg",
      "source": "data:image/svg+xml;base64,...",
      "fileName2": "image2.svg",
      "source2": "data:image/svg+xml;base64,..."
    }
  ]
}
```

**Response (No Duplicates):**
```json
{
  "isSuccess": true,
  "message": "No duplicate images found.",
  "data": []
}
```

## Frontend Entegrasyonu

Frontend kodları ayrı repoda tutulduğu için, sadece API kullanım şekli:

### 1. Dosya Upload
```javascript
// 1. Dosyaları upload et
const formData = new FormData();
files.forEach(file => formData.append('file', file));

const uploadResponse = await fetch('/upload', {
    method: 'POST',
    body: formData
});
const { jobId } = await uploadResponse.json();
```

### 2. Progress Monitoring
```javascript
// 2. Progress takip et
const checkProgress = async () => {
    const response = await fetch(`/status/${jobId}`);
    const { job } = await response.json();
    
    if (job.status === 'completed') {
        // Sonuçları al
        const resultResponse = await fetch(`/result/${jobId}`);
        const result = await resultResponse.json();
        // Sonuçları göster
    } else if (job.status === 'processing') {
        // Progress göster: job.progress.percentage
        setTimeout(checkProgress, 2000); // 2 saniye sonra tekrar kontrol et
    }
};
```

## Performance Optimizations

1. **Batch Processing**: Küçük gruplar halinde işleme
2. **Image Resizing**: 300x300 pixel'e küçültme
3. **Thread Pool**: 4 worker thread
4. **Memory Management**: Geçici dosya temizleme
5. **Job Cleanup**: Eski job'ları otomatik silme (1 saat)

## Environment Variables

```bash
# Upload limits
UPLOAD_FOLDER=/tmp/svg_uploads
JOBS_FOLDER=/tmp/svg_jobs

# Processing limits
MAX_WORKERS=4
BATCH_SIZE=5

# Job management
JOB_CLEANUP_HOURS=2
MAX_CONCURRENT_JOBS=10
```

## Deployment Checklist

### For Production:

1. **Use Async Server**
   ```bash
   python async_server.py
   ```

2. **Configure Reverse Proxy** (Nginx)
   ```nginx
   server {
       location / {
           proxy_pass http://127.0.0.1:5000;
           proxy_timeout 300s;
           client_max_body_size 100M;
           proxy_read_timeout 300s;
           proxy_connect_timeout 300s;
           proxy_send_timeout 300s;
       }
   }
   ```

3. **Environment Variables**
   ```bash
   export MAX_WORKERS=4
   export BATCH_SIZE=5
   export JOB_CLEANUP_HOURS=2
   ```

4. **Monitor Resources**
   - CPU usage during processing
   - Memory usage for large files
   - Disk space for temporary files

### For Docker Deployment:

1. Build with async Dockerfile:
   ```bash
   docker build -f Dockerfile.async -t svg-finder .
   ```

2. Run with proper resource limits:
   ```bash
   docker run -p 5000:5000 \
     -e MAX_WORKERS=4 \
     -e BATCH_SIZE=5 \
     --memory=2g \
     --cpus=2 \
     svg-finder
   ```

## Troubleshooting

### Timeout Issues
- ✅ Use `async_server.py` instead of `server.py`
- ✅ Configure proper timeouts in reverse proxy
- ✅ Monitor job status via `/status/{jobId}` endpoint

### High Memory Usage
- ✅ Reduce `BATCH_SIZE` environment variable
- ✅ Reduce `MAX_WORKERS` for limited memory
- ✅ Enable job cleanup

### Slow Processing
- ✅ Increase `MAX_WORKERS` for more CPU cores
- ✅ Use SSD storage for temporary files
- ✅ Optimize image resize dimensions

### CORS Issues
- ✅ CORS already enabled for all routes
- ✅ If needed, configure specific origins in production

## Migration from Sync to Async

### Eski server.py'den async_server.py'ye geçiş:

1. **Backend'i değiştir:**
   ```bash
   # Eski
   python server.py
   
   # Yeni
   python async_server.py
   ```

2. **Frontend'de değişiklik gerekli:**
   - Upload response'da `jobId` field'ı kullan
   - `/status/{jobId}` endpoint'ini poll et
   - `/result/{jobId}` endpoint'inden sonucu al

3. **API response formatı değişti:**
   ```json
   // Eski (sync)
   {
     "isSuccess": true,
     "data": [...],
     "message": "..."
   }
   
   // Yeni (async)
   {
     "isSuccess": true,
     "jobId": "uuid",
     "message": "Processing started..."
   }
   ```

## File Structure

```
.
├── async_server.py          # Asenkron server (ÖNERİLEN)
├── server.py                # Eski senkron server
├── production.py            # Production config
├── Dockerfile.async         # Production Dockerfile
├── Dockerfile               # Eski Dockerfile
├── requirements.txt         # Dependencies
└── README.md               # Bu dosya
``` 