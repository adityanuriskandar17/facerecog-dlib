# Redis Setup untuk GCP Cloud Run

## 🚀 Overview
Redis cache telah diintegrasikan ke dalam aplikasi face recognition untuk meningkatkan performa di GCP Cloud Run.

## 📋 Konfigurasi Environment Variables

### Local Development
```bash
# .env file
REDIS_ENABLED=false
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
```

### GCP Cloud Run
```bash
# Environment variables di Cloud Run
REDIS_ENABLED=true
REDIS_HOST=your-redis-instance-ip
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password
REDIS_DB=0
```

## 🛠 Setup Redis di GCP

### Option 1: Google Cloud Memorystore (Recommended)
```bash
# Create Redis instance
gcloud redis instances create face-recognition-cache \
    --size=1 \
    --region=asia-southeast2 \
    --redis-version=redis_6_x \
    --tier=basic

# Get connection info
gcloud redis instances describe face-recognition-cache \
    --region=asia-southeast2
```

### Option 2: Redis Cloud (External)
1. Sign up di https://redis.com/
2. Create new database
3. Get connection details
4. Update environment variables

### Option 3: Self-hosted Redis
```bash
# Deploy Redis sebagai Cloud Run service
gcloud run deploy redis-server \
    --image=redis:alpine \
    --port=6379 \
    --memory=1Gi \
    --cpu=1 \
    --region=asia-southeast2
```

## 🔧 Endpoints Baru

### Redis Status
```
GET /redis_status
```
Check Redis connection dan cache status.

### Clear Cache
```
GET /redis_clear_cache
```
Hapus semua cached encodings.

### Force Reload
```
GET /redis_reload
```
Force reload encodings dari database dan update cache.

## 📊 Cara Kerja

1. **Startup**: Aplikasi coba connect ke Redis
2. **First Load**: Load encodings dari database, cache ke Redis
3. **Subsequent Loads**: Load dari Redis cache (jauh lebih cepat)
4. **Cache Expiry**: Cache expired setelah 1 jam
5. **Auto Update**: Cache otomatis update ketika ada member baru

## 🎯 Benefits

- **Faster Startup**: Load encodings dari Redis jauh lebih cepat
- **Persistent Cache**: Cache tetap ada meski instance restart
- **Memory Efficient**: Tidak perlu load semua encodings ke memory
- **Auto Recovery**: Fallback ke database jika Redis down

## 🚨 Troubleshooting

### Redis Connection Failed
```
[REDIS] Failed to connect to Redis: [Errno 111] Connection refused
```
**Solution**: Check Redis server status dan network connectivity

### Cache Not Working
```
[REDIS] No cached encodings found with key: face_encodings
```
**Solution**: Call `/redis_reload` untuk populate cache

### Memory Issues
```
[REDIS] Failed to cache encodings: Memory limit exceeded
```
**Solution**: Increase Redis memory atau reduce batch size

## 📈 Performance Comparison

| Scenario | Without Redis | With Redis |
|----------|---------------|------------|
| First Load | 30-60 seconds | 30-60 seconds |
| Subsequent Loads | 30-60 seconds | 1-3 seconds |
| Memory Usage | High | Low |
| Instance Startup | Slow | Fast |

## 🔄 Migration Guide

1. **Enable Redis**: Set `REDIS_ENABLED=true`
2. **Configure Connection**: Update Redis connection details
3. **Deploy**: Deploy ke Cloud Run
4. **Test**: Call `/redis_status` untuk verify
5. **Populate Cache**: Call `/redis_reload` untuk initial cache

## 💡 Tips

- Use Redis Cloud untuk production (managed service)
- Set appropriate memory size (1GB recommended)
- Monitor Redis memory usage
- Set up Redis monitoring/alerting
- Use Redis persistence untuk critical data
