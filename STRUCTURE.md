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
