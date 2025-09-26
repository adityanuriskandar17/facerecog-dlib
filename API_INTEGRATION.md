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
