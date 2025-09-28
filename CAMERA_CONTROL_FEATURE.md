# Fitur Kontrol Kamera - Halaman Retake Foto

## Perubahan yang Dilakukan

### 1. HTML Template (`app/templates/retake.html`)
- **Menghapus file input**: Tidak ada lagi opsi upload file
- **Menambahkan preview kamera**: Video element untuk preview kamera real-time
- **Tombol kontrol kamera**:
  - `Mulai Kamera`: Membuka akses kamera
  - `Ambil Foto`: Mengambil foto saat user siap
  - `Stop Kamera`: Menghentikan kamera tanpa mengambil foto
  - `Reset`: Reset semua dan kembali ke keadaan awal

### 2. JavaScript (`app/static/js/retake.js`)
- **Kontrol penuh user**: User bisa memposisikan diri sebelum mengambil foto
- **Preview real-time**: Video stream ditampilkan untuk user bisa melihat posisi
- **Manajemen stream**: Proper cleanup saat stop atau reset
- **Error handling**: Pesan error yang jelas untuk berbagai kondisi

### 3. CSS (`app/static/css/retake.css`)
- **Menghapus styling file input**: Tidak diperlukan lagi
- **Responsive design**: Tetap mendukung berbagai ukuran layar

## Cara Kerja

1. **Mulai Kamera**: User klik "Mulai Kamera" → Kamera aktif, preview ditampilkan
2. **Posisikan Diri**: User bisa melihat preview dan memposisikan diri
3. **Ambil Foto**: User klik "Ambil Foto" saat siap → Foto diambil dan preview kamera ditutup
4. **Stop Kamera**: User bisa klik "Stop Kamera" untuk membatalkan tanpa mengambil foto
5. **Reset**: Kembali ke keadaan awal, hapus foto yang sudah diambil

## Keuntungan

- ✅ **User Control**: User punya kontrol penuh kapan mengambil foto
- ✅ **Preview Real-time**: Bisa melihat posisi sebelum mengambil foto
- ✅ **Tidak Ada Upload**: Hanya capture dari kamera, lebih aman
- ✅ **User Experience**: Lebih intuitif dan user-friendly
- ✅ **Error Handling**: Pesan error yang jelas

## File yang Dimodifikasi

- `app/templates/retake.html` - Template HTML
- `app/static/js/retake.js` - JavaScript logic
- `app/static/css/retake.css` - Styling (minor cleanup)

## Testing

Aplikasi berjalan di `http://127.0.0.1:8001` dan fitur kamera sudah berfungsi dengan kontrol penuh user.



REDIS

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


MAP TREE

# Face Recognition System - Refactored Structure

## 📁 Struktur Folder Baru

```
DLIB/
├── app/                          # Main application package
│   ├── __init__.py              # Flask app factory
│   ├── config/                  # Configuration
│   │   └── __init__.py         # Environment variables & settings
│   ├── blueprints/              # Flask blueprints (routes)
│   │   ├── __init__.py
│   │   ├── auth.py             # Authentication routes (login, logout)
│   │   ├── main.py             # Main routes (retake, recognition)
│   │   ├── recognition.py      # Recognition API routes
│   │   └── admin.py            # Admin/debug routes
│   ├── services/                # Business logic services
│   │   ├── __init__.py
│   │   ├── database_service.py # Database operations
│   │   ├── face_recognition_service.py # Face recognition utilities
│   │   ├── recognition_service.py # Main recognition logic
│   │   ├── redis_service.py    # Redis caching
│   │   └── door_service.py     # Door management
│   ├── templates/               # HTML templates
│   │   ├── login.html
│   │   ├── retake.html
│   │   └── recognition.html
│   └── static/                  # Static files
│       ├── css/
│       │   ├── login.css
│       │   ├── retake.css
│       │   └── recognition.css
│       └── js/
│           ├── retake.js
│           └── recognition.js
├── app.py                       # Main application entry point
├── app_old.py                   # Backup of original app.py
└── requirements.txt             # Dependencies
```

## 🔧 Komponen Utama

### 1. **Blueprints (Routes)**
- **auth.py**: Authentication (login, logout)
- **main.py**: Main pages (retake, recognition)
- **recognition.py**: Recognition API endpoints
- **admin.py**: Admin/debug endpoints

### 2. **Services (Business Logic)**
- **database_service.py**: Database operations
- **recognition_service.py**: Face recognition logic
- **redis_service.py**: Caching operations
- **face_recognition_service.py**: Face recognition utilities
- **door_service.py**: Door management

### 3. **Configuration**
- **config/__init__.py**: Environment variables & settings

### 4. **Templates & Static Files**
- **templates/**: HTML templates
- **static/css/**: CSS stylesheets
- **static/js/**: JavaScript files

## 🚀 Cara Menjalankan

### 1. Install Dependencies
```bash
pip3 install -r requirements.txt
```

### 2. Setup Environment Variables
Copy `env_example.txt` ke `.env` dan sesuaikan konfigurasi:
```bash
cp env_example.txt .env
```

### 3. Jalankan Aplikasi
```bash
python3 app.py
```

## 🔄 Perubahan dari Versi Lama

### ✅ Yang Sudah Dipisah:
1. **HTML Templates** → `app/templates/`
2. **CSS Styles** → `app/static/css/`
3. **JavaScript** → `app/static/js/`
4. **Routes** → `app/blueprints/`
5. **Business Logic** → `app/services/`
6. **Configuration** → `app/config/`

### 🎯 Keuntungan Struktur Baru:
- **Modularity**: Setiap komponen terpisah dengan jelas
- **Maintainability**: Mudah di-maintain dan di-debug
- **Scalability**: Mudah menambah fitur baru
- **Team Development**: Multiple developer bisa bekerja parallel
- **Testing**: Mudah untuk unit testing
- **Code Reusability**: Service bisa digunakan ulang

## 📋 Routes Mapping

### Authentication Routes (`/auth`)
- `GET/POST /login` → Login page
- `GET /logout` → Logout

### Main Routes (`/main`)
- `GET /` → Redirect to retake
- `GET /retake` → Retake photo page
- `GET /recognition` → Face recognition page

### Recognition API (`/recognition`)
- `POST /update_door_id` → Update door ID
- `POST /recognize` → Face recognition API
- `GET /reload` → Reload encodings
- `GET /health` → Health check

### Admin Routes (`/admin`)
- `GET /check_new_members` → Check new members
- `GET /regenerate_enc` → Regenerate encodings
- `GET /enc_status` → Encoding status
- `GET /debug_members` → Debug members
- `POST /set_auto_check_interval` → Set auto-check interval
- `GET /gcp_debug` → GCP debug
- `GET /gcp_load_on_demand` → GCP load on demand
- `GET /redis_status` → Redis status
- `GET /redis_clear_cache` → Clear Redis cache
- `GET /redis_reload` → Redis reload

## 🔧 Development Tips

### Menambah Route Baru:
1. Buat route di blueprint yang sesuai
2. Import service yang diperlukan
3. Update blueprint registration di `app/__init__.py`

### Menambah Service Baru:
1. Buat file baru di `app/services/`
2. Import di blueprint yang membutuhkan
3. Gunakan dependency injection jika diperlukan

### Menambah Template Baru:
1. Buat file HTML di `app/templates/`
2. Buat CSS di `app/static/css/`
3. Buat JS di `app/static/js/`
4. Update route untuk render template

## 🐛 Troubleshooting

### Import Error:
- Pastikan semua dependencies terinstall
- Check Python path dan virtual environment

### Template Not Found:
- Pastikan template ada di `app/templates/`
- Check Flask app configuration

### Service Error:
- Check database connection
- Verify Redis connection
- Check environment variables

## 📝 Notes

- File `app_old.py` adalah backup dari versi lama
- Struktur ini mengikuti Flask best practices
- Semua routes menggunakan blueprints untuk modularity
- Services dipisah berdasarkan domain (database, recognition, etc.)
- Configuration terpusat di `app/config/`


DLIB/
├── app/                          # Main application package
│   ├── __init__.py              # Flask app factory ✅
│   ├── config/                  # Configuration ✅
│   ├── blueprints/              # Routes (modular) ✅
│   │   ├── auth.py             # Authentication ✅
│   │   ├── main.py             # Main pages ✅
│   │   ├── recognition.py      # Recognition API ✅
│   │   └── admin.py            # Admin/debug ✅
│   ├── services/                # Business logic ✅
│   │   ├── database_service.py # Database ops ✅
│   │   ├── recognition_service.py # Face recognition ✅
│   │   ├── redis_service.py    # Caching ✅
│   │   ├── face_recognition_service.py # Utils ✅
│   │   └── door_service.py     # Door management ✅
│   ├── templates/               # HTML templates ✅
│   │   ├── login.html
│   │   ├── retake.html
│   │   └── recognition.html
│   └── static/                  # Static files ✅
│       ├── css/
│       └── js/
└── app.py                       # Main entry point ✅


-- Migration: Add 'enc' field to member table for storing face encodings
-- Run this SQL to add the encoding field to your member table

-- Check if the field already exists (optional)
SELECT COLUMN_NAME 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_SCHEMA = 'deepface' AND TABLE_NAME = 'member' AND COLUMN_NAME = 'enc';

-- Add the 'enc' field to store face encodings as binary data
ALTER TABLE member ADD COLUMN enc LONGBLOB NULL;

-- Add index for better performance (optional)
CREATE INDEX idx_member_enc ON member(enc(100));

-- Verify the field was added
DESCRIBE member;


Sistem Sekarang:

    ✅ Tidak membaca dari field enc - Bagian loading dari database dikomentar
    ✅ Tidak menyimpan ke field enc - Bagian penyimpanan ke database dikomentar
    ✅ Selalu generate dari gambar - Setiap kali startup, generate encoding baru
    ✅ Tidak ada operasi database - Tidak ada read/write ke field enc
    ✅ Aplikasi berjalan normal - Bisa diakses di http://127.0.0.1:8001
Perilaku Sekarang:

Startup: Generate encoding dari gambar untuk semua member

Tidak ada caching: Encoding tidak disimpan ke database

Fresh generation: Setiap kali restart, generate ulang semua encoding

No DB operations: Tidak ada operasi read/write ke field enc

Untuk Mengembalikan ke Mode Database:
Jika nanti ingin menggunakan field enc lagi, tinggal hapus tanda # dari:
    Baris # stored_encoding = load_encoding_from_db(member_id)
    Baris # save_encoding_to_db(member_id, encoding[0])

Dan semua baris yang terkait di dalam blok if/else
Sekarang sistem akan selalu generate encoding dari gambar setiap kali startup tanpa menyimpan atau membaca dari database!


✅ Code untuk Membuat ENC Otomatis ke Database
Fitur yang Sudah Diimplementasikan:
    Automatic ENC Field Creation (add_enc_field_to_member_table())
        Otomatis menambahkan field enc ke table member jika belum ada
        Field type: LONGBLOB untuk menyimpan binary encoding data

    Smart ENC Loading (load_encoding_from_db())
        Load ENC dari database jika tersedia
        Validasi ukuran ENC (harus 128 float64 values = 1024 bytes)
        Return None jika ENC tidak valid atau tidak ada

    Automatic ENC Generation (build_known_encodings())
        PRIORITAS PERTAMA: Coba load ENC dari database
        FALLBACK: Generate ENC baru dari gambar jika tidak ada di DB
        AUTO SAVE: Simpan ENC yang baru di-generate ke database

    ENC Regeneration Function (regenerate_missing_encodings())
        Regenerate ENC untuk semua member yang tidak punya ENC valid
        Bisa dipanggil manual atau otomatis saat startup

    New API Endpoints:
        GET /enc_status - Cek status ENC semua member
        GET /regenerate_enc - Manual trigger regenerasi ENC
        
    Startup Auto-Processing:
        Otomatis cek dan regenerate ENC yang hilang saat server start
        Log detail proses untuk monitoring


        API INTEGRATION

        # GymMaster API Integration

## 🔗 **API Endpoints yang Digunakan**

### 1. **Login Endpoint**
```
POST https://ftl.gymmasteronline.com/portal/api/v1/login
```

**Request Body:**
```json
{
    "api_key": "840cb15c99c1fe05ef395e2b3c526f4b",
    "email": "user@example.com",
    "password": "password123"
}
```

**Response:**
```json
{
    "error": null,
    "result": {
        "token": "user_token_here",
        "expires": "2025-12-31T23:59:59Z"
    }
}
```

### 2. **Profile Endpoint**
```
GET https://ftl.gymmasteronline.com/portal/api/v1/member/profile?token={token}&api_key={api_key}
```

**Response:**
```json
{
    "error": null,
    "result": {
        "id": 114955,
        "firstname": "NURMALA",
        "surname": "TIRZA RAHAYU",
        "fullname": "NURMALA TIRZA RAHAYU",
        "email": "tirza.rahayu@gmail.com",
        "memberphoto": "https://ftl.gymmasteronline.com/static/m-img/4e3664ab30a861ebfe19fac5316308a0.jpg",
        "clubname": "FTL - Menteng",
        "status": "Current"
    }
}
```

## 🖼️ **Foto Profile Integration**

### **Flow Foto Profile:**
1. **Login** → Dapatkan token dari API
2. **Retake Page** → Panggil profile API dengan token
3. **Display** → Tampilkan `memberphoto` dari response API
4. **Update** → Jika user upload foto baru, update ke database lokal

### **Konfigurasi Environment:**
```env
# Gym API Configuration
GYM_API_KEY=840cb15c99c1fe05ef395e2b3c526f4b
GYM_BASE_URL=https://ftl.gymmasteronline.com
GYM_LOGIN_URL=https://ftl.gymmasteronline.com/portal/api/v1/login
GYM_PROFILE_URL=https://ftl.gymmasteronline.com/portal/api/v1/member/profile
```

## 🔧 **Implementasi di Code**

### **Auth Blueprint (`app/blueprints/auth.py`):**
```python
def fetch_member_profile(token: str) -> dict:
    """Fetch member profile from gym API"""
    try:
        params = {"token": token, "api_key": GYM_API_KEY}
        r = requests.get(GYM_PROFILE_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}
```

### **Main Blueprint (`app/blueprints/main.py`):**
```python
@main_bp.route("/retake")
def retake():
    """Retake photo page"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    token = session.get("gm_token", "")
    current_photo = ""
    if token:
        prof = fetch_member_profile(token)
        try:
            if not prof.get("error") and prof.get("result"):
                current_photo = prof["result"].get("memberphoto") or ""
        except Exception:
            current_photo = ""
    
    return render_template("retake.html", current_photo=current_photo)
```

### **Template (`app/templates/retake.html`):**
```html
<img id="currentPhoto" class="preview" 
     src="{{ current_photo }}" 
     onerror="this.src=''; this.alt='No photo';" />
```

## 🎯 **Fitur yang Sudah Diimplementasi**

### ✅ **Foto Saat Ini:**
- Mengambil foto dari API GymMaster
- Menampilkan di halaman retake
- Fallback jika foto tidak ada

### ✅ **Authentication:**
- Login dengan email/password
- Token management
- Session handling

### ✅ **API Integration:**
- Profile endpoint integration
- Error handling
- Timeout handling

## 🔄 **Flow Lengkap**

1. **User Login** → `POST /login`
2. **Get Token** → Simpan di session
3. **Access Retake** → `GET /retake`
4. **Fetch Profile** → Call GymMaster API
5. **Display Photo** → Tampilkan `memberphoto`
6. **User Action** → Upload foto baru atau ambil foto

## 🛠️ **Error Handling**

### **API Errors:**
- Network timeout
- Invalid token
- API server error
- Missing photo

### **Fallback:**
- Default "No photo" message
- Graceful error handling
- User-friendly messages

## 📱 **User Experience**

### **Halaman Retake:**
- **Foto Saat Ini**: Menampilkan foto dari GymMaster
- **Preview Foto Baru**: Upload atau ambil foto baru
- **Petunjuk**: Instruksi pengambilan foto yang jelas
- **Navigation**: Link ke Face Recognition

### **Responsive Design:**
- Mobile-friendly
- Clean interface
- Easy navigation

## 🔐 **Security**

### **Token Management:**
- Secure session storage
- Token validation
- Automatic logout on expiry

### **API Security:**
- API key protection
- HTTPS endpoints
- Request timeout

## 📊 **Monitoring**

### **Logs:**
- API call logs
- Error tracking
- Performance monitoring

### **Debug Info:**
- Token status
- API response
- Error details
