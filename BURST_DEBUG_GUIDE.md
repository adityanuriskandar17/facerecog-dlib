# 🔍 Debug Guide: Burst Face Recognition Tidak Menyimpan ENC

## ❌ **Masalah:**
Burst face recognition (20 foto) tidak menyimpan encoding ke `member.enc` padahal sebelumnya bisa.

## 🔍 **Analisis Masalah:**

### **1. Database Status:**
```
✅ Email column: Ada (117,709 members dengan email)
❌ ENC data: 0 members dengan enc data
✅ ENC column: Ada (longblob)
```

### **2. Sistem Burst Face Recognition:**
- ✅ Endpoint: `/compare-photo-burst`
- ✅ Fungsi save: `save_encoding_to_db(member_db_id, enc_avg)`
- ❌ **Kondisi**: Hanya save jika `target_email` ada dan valid

## 🛠️ **Solusi Debugging:**

### **Step 1: Cek Request Data**
```javascript
// Di browser console, cek apakah email dikirim:
console.log('Email:', window.CURRENT_EMAIL);
console.log('Images count:', images.length);
```

### **Step 2: Cek Response dari Server**
```javascript
// Di retake.js, tambahkan logging:
const res = await fetch('/compare-photo-burst', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ images, email })
});

const json = await res.json();
console.log('Server response:', json);
console.log('Saved:', json.saved);
console.log('Save reason:', json.save_reason);
console.log('Member ID:', json.member_id);
```

### **Step 3: Cek Database Query**
```python
# Test query yang digunakan sistem:
SELECT id FROM member WHERE email = 'your_email@example.com' LIMIT 1
```

## 🔧 **Kemungkinan Penyebab:**

### **1. Email Tidak Dikirim**
```javascript
// Cek di retake.js line 227:
const email = (window.CURRENT_EMAIL || '').trim()
console.log('Email being sent:', email);
```

### **2. Email Tidak Ditemukan di Database**
```sql
-- Cek apakah email ada di database:
SELECT id, email FROM member WHERE email = 'your_email@example.com';
```

### **3. Error dalam save_encoding_to_db**
```python
# Cek error di server log:
[COMPARE_BURST] Save error: [error_message]
```

## 🚀 **Solusi Perbaikan:**

### **Option 1: Tambahkan Logging**
```python
# Di compare_photo_burst endpoint, tambahkan logging:
print(f"[COMPARE_BURST] Target email: {target_email}")
print(f"[COMPARE_BURST] Email found: {row is not None}")
print(f"[COMPARE_BURST] Member ID: {member_db_id}")
print(f"[COMPARE_BURST] Save result: {saved}")
```

### **Option 2: Fallback Save Method**
```python
# Jika email tidak ditemukan, coba save dengan member_id langsung
if not saved and member_id:
    try:
        save_encoding_to_db(member_id, enc_avg.astype(np.float64))
        saved = True
        save_reason = "saved_by_member_id"
    except Exception as e:
        save_reason = f"fallback_error: {e}"
```

### **Option 3: Manual Save Endpoint**
```python
# Buat endpoint khusus untuk save encoding:
@recognition_bp.route("/save-encoding", methods=["POST"])
def save_encoding():
    data = request.get_json()
    member_id = data.get("member_id")
    encoding_data = data.get("encoding")
    
    if member_id and encoding_data:
        save_encoding_to_db(member_id, np.array(encoding_data))
        return {"success": True}
    return {"success": False, "error": "Missing data"}
```

## 🔍 **Debug Steps:**

### **1. Cek Frontend**
```bash
# Buka browser console dan cek:
console.log('CURRENT_EMAIL:', window.CURRENT_EMAIL);
```

### **2. Cek Network Request**
```bash
# Di browser DevTools > Network, cek request ke /compare-photo-burst:
# - Method: POST
# - Body: {"images": [...], "email": "..."}
```

### **3. Cek Server Logs**
```bash
# Cek server console untuk error messages:
[COMPARE_BURST] Save error: [error]
[COMPARE_BURST] Target email: [email]
```

### **4. Test Database Query**
```sql
-- Test query yang digunakan sistem:
SELECT id, email FROM member WHERE email = 'test@example.com';
```

## 🎯 **Quick Fix:**

### **Temporary Solution:**
```python
# Di compare_photo_burst, tambahkan fallback:
if not saved and not target_email:
    # Try to get member_id from session or request
    member_id = session.get('member_id') or request.args.get('member_id')
    if member_id:
        save_encoding_to_db(int(member_id), enc_avg.astype(np.float64))
        saved = True
        save_reason = "saved_by_session_member_id"
```

## 📊 **Expected Results:**

### **Jika Berhasil:**
```json
{
  "success": true,
  "saved": true,
  "member_id": 123,
  "save_reason": null
}
```

### **Jika Gagal:**
```json
{
  "success": true,
  "saved": false,
  "member_id": null,
  "save_reason": "email_not_found"
}
```

## 🚨 **Common Issues:**

1. **Email tidak dikirim dari frontend**
2. **Email tidak ditemukan di database**
3. **Error dalam save_encoding_to_db function**
4. **Permission issue pada database**
5. **Email format tidak valid**

**Langkah selanjutnya: Cek server logs dan frontend console untuk error messages!**
