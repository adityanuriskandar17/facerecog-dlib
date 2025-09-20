import os
import io
import time
import threading
from typing import Dict, List, Tuple
from collections import OrderedDict

import cv2
import numpy as np
import requests
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
from flask import Flask, Response, render_template_string

# ==== Dlib via face_recognition ====
import face_recognition  # built on top of dlib

# ===================== Config =====================
load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "deepface")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

TOLERANCE = 0.45  # lebih ketat dari default 0.6

# Jika ingin batasi request gambar (detik)
REQUEST_TIMEOUT = 15

# Gym API Configuration
GYM_API_KEY = os.getenv("GYM_API_KEY", "")
GYM_DOOR_ID = os.getenv("GYM_DOOR_ID", "19456")
GYM_LOGIN_URL = os.getenv("GYM_LOGIN_URL", "")
GYM_GATE_URL = os.getenv("GYM_GATE_URL", "")


# ===================== DB Helpers =====================
def get_conn():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        autocommit=True,
    )

def fetch_member_images() -> List[Tuple[int, str, str]]:
    """
    Ambil (member_id, first_name, full_url) untuk foto terbaru per member yang aktif.
    Kita ambil semua kemudian reduce ke 'latest per member_id'.
    """
    sql = """
    SELECT
        m.id AS member_id,
        m.member_id AS gym_member_id,
        COALESCE(m.first_name, CONCAT('Member_', m.id)) AS first_name,
        CONCAT(f.file_base_url, f.file_base_path, f.file_path, f.file_name) AS full_url,
        f.created_at
    FROM member m
    JOIN member_file f ON f.member_id = m.id
    WHERE m.status = 1
      AND (f.status IS NULL OR f.status = 1)
      AND (f.file_type_id IS NULL OR f.file_type_id = 1)
    ORDER BY m.id ASC, f.created_at DESC
    """
    rows: List[Tuple[int, int, str, str, str]] = []
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Error as e:
        print(f"[DB] Error: {e}")
        return []

    latest_per_member: "OrderedDict[int, Tuple[int,int,str,str]]" = OrderedDict()
    for member_id, gym_member_id, first_name, full_url, created_at in rows:
        if member_id not in latest_per_member:
            latest_per_member[member_id] = (member_id, gym_member_id, first_name, full_url)
    return list(latest_per_member.values())

# ===================== Image / Encoding =====================
def url_to_rgb_array(url: str) -> np.ndarray:
    """
    Download image from URL (supports querystrings), return RGB numpy array.
    Raises on error / if not an image.
    """
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = np.frombuffer(resp.content, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Gagal decode image dari URL")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return rgb

def add_enc_field_to_member_table():
    """
    Add 'enc' field to member table if it doesn't exist
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if enc field exists
        cur.execute("""
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'member' AND COLUMN_NAME = 'enc'
        """, (MYSQL_DATABASE,))
        
        if not cur.fetchone():
            print("[DB] Adding 'enc' field to member table...")
            cur.execute("ALTER TABLE member ADD COLUMN enc LONGBLOB NULL")
            conn.commit()
            print("[DB] 'enc' field added successfully")
        else:
            print("[DB] 'enc' field already exists")
        
        cur.close()
        conn.close()
    except Error as e:
        print(f"[DB] Error adding enc field: {e}")

def save_encoding_to_db(member_id: int, encoding: np.ndarray):
    """
    Save face encoding to member table
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Convert numpy array to binary
        encoding_bytes = encoding.tobytes()
        
        cur.execute("UPDATE member SET enc = %s WHERE id = %s", (encoding_bytes, member_id))
        conn.commit()
        
        cur.close()
        conn.close()
        print(f"[DB] Saved encoding for member_id={member_id}")
    except Error as e:
        print(f"[DB] Error saving encoding for member_id={member_id}: {e}")

def load_encoding_from_db(member_id: int) -> np.ndarray:
    """
    Load face encoding from member table
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT enc FROM member WHERE id = %s", (member_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result and result[0]:
            return np.frombuffer(result[0], dtype=np.float64)
        return None
    except Error as e:
        print(f"[DB] Error loading encoding for member_id={member_id}: {e}")
        return None

def build_known_encodings() -> Tuple[List[np.ndarray], List[str], List[int], Dict[int, int]]:
    """
    Return (encodings, names, member_ids, gym_member_id_mapping)
    - Load from database first, generate if not exists
    """
    # Ensure enc field exists
    add_enc_field_to_member_table()
    
    sources = fetch_member_images()
    encodings: List[np.ndarray] = []
    names: List[str] = []
    member_ids: List[int] = []
    gym_member_id_mapping: Dict[int, int] = {}  # member_id -> gym_member_id
    skipped: List[Tuple[int, str]] = []

    print(f"[ENC] Mulai load {len(sources)} member image(s)")
    for member_id, gym_member_id, first_name, full_url in sources:
        try:
            # Try to load from database first
            stored_encoding = load_encoding_from_db(member_id)
            
            if stored_encoding is not None:
                # Use stored encoding
                encodings.append(stored_encoding)
                names.append(first_name.strip() or f"Member_{member_id}")
                member_ids.append(member_id)
                gym_member_id_mapping[member_id] = gym_member_id
                print(f"[ENC] Loaded from DB member_id={member_id} name={names[-1]}")
            else:
                # Generate new encoding from image
                print(f"[ENC] Generating new encoding for member_id={member_id}")
                img = url_to_rgb_array(full_url)
                boxes = face_recognition.face_locations(img, model="hog")
            if not boxes:
                print(f"[ENC] Wajah tidak ditemukan di member_id={member_id} url={full_url}")
                skipped.append((member_id, "no_face"))
                continue
                
            # Ambil wajah pertama
            encoding = face_recognition.face_encodings(img, known_face_locations=[boxes[0]])
            if not encoding:
                print(f"[ENC] Encoding gagal di member_id={member_id}")
                skipped.append((member_id, "no_encoding"))
                continue
                
                # Save to database
                save_encoding_to_db(member_id, encoding[0])
                
            encodings.append(encoding[0])
            names.append(first_name.strip() or f"Member_{member_id}")
            member_ids.append(member_id)
            gym_member_id_mapping[member_id] = gym_member_id
            print(f"[ENC] Generated & saved member_id={member_id} name={names[-1]}")
                
        except Exception as e:
            print(f"[ENC] Error for member_id={member_id}: {e}")
            skipped.append((member_id, "error"))

    print(f"[ENC] Selesai. OK={len(encodings)} Skip={len(skipped)}")
    return encodings, names, member_ids, gym_member_id_mapping

# ===================== Gym API Integration =====================
def gym_login(member_id: int) -> dict:
    """
    Login to gym system and get token
    """
    try:
        payload = {
            "api_key": GYM_API_KEY,
            "memberid": member_id
        }
        
        response = requests.post(GYM_LOGIN_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get("error") is None and data.get("result"):
            token = data["result"]["token"]
            expires = data["result"]["expires"]
            print(f"[GYM] Login successful for member_id={member_id}")
            return {"success": True, "token": token, "expires": expires}
        else:
            print(f"[GYM] Login failed for member_id={member_id}: {data.get('error', 'Unknown error')}")
            return {"success": False, "error": data.get("error", "Unknown error")}
            
    except requests.exceptions.RequestException as e:
        print(f"[GYM] Login request failed for member_id={member_id}: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"[GYM] Login error for member_id={member_id}: {e}")
        return {"success": False, "error": str(e)}

def gym_open_gate(token: str) -> dict:
    """
    Open gym gate using token
    """
    try:
        payload = {
            "api_key": GYM_API_KEY,
            "doorid": GYM_DOOR_ID,
            "token": token
        }
        
        
        response = requests.post(GYM_GATE_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get("error") is None:
            print(f"[GYM] Gate opened successfully")
            return {"success": True, "message": "Gate opened successfully"}
        else:
            print(f"[GYM] Gate open failed: {data.get('error', 'Unknown error')}")
            return {"success": False, "error": data.get("error", "Unknown error")}
            
    except requests.exceptions.RequestException as e:
        print(f"[GYM] Gate open request failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"[GYM] Gate open error: {e}")
        return {"success": False, "error": str(e)}

def process_member_detection(member_id: int, member_name: str) -> dict:
    """
    Process member detection: login and open gate
    """
    print(f"[GYM] Processing detection for {member_name} (ID: {member_id})")
    
    # Step 1: Login to get token
    login_result = gym_login(member_id)
    if not login_result["success"]:
        return {"success": False, "error": f"Login failed: {login_result['error']}"}
    
    # Step 2: Open gate using token
    gate_result = gym_open_gate(login_result["token"])
    if not gate_result["success"]:
        return {"success": False, "error": f"Gate open failed: {gate_result['error']}"}
    
    return {"success": True, "message": f"Welcome {member_name}! Gate opened successfully."}

# ===================== Video / Recognition =====================
class Recognizer:
    def __init__(self):
        self.known_encodings: List[np.ndarray] = []
        self.known_names: List[str] = []
        self.known_ids: List[int] = []
        self.gym_member_id_mapping: Dict[int, int] = {}  # member_id -> gym_member_id
        self.lock = threading.Lock()
        self.last_reload = 0
        self.last_successful_login = 0  # Timestamp of last successful login
        self.last_successful_member = ""  # Name of last successful member
        self.cooldown_duration = 10  # 10 seconds cooldown

    def reload(self):
        with self.lock:
            self.known_encodings, self.known_names, self.known_ids, self.gym_member_id_mapping = build_known_encodings()
            self.last_reload = time.time()
    
    def is_in_cooldown(self):
        """Check if system is in cooldown period"""
        current_time = time.time()
        return (current_time - self.last_successful_login) < self.cooldown_duration
    
    def get_cooldown_remaining(self):
        """Get remaining cooldown time in seconds"""
        current_time = time.time()
        elapsed = current_time - self.last_successful_login
        remaining = self.cooldown_duration - elapsed
        return max(0, remaining)
    
    def set_successful_login(self, member_name: str):
        """Mark successful login timestamp and store member name"""
        self.last_successful_login = time.time()
        self.last_successful_member = member_name

    def recognize_frame(self, frame_bgr: np.ndarray) -> np.ndarray:
        """
        Detect & recognize faces in BGR frame. Draw boxes & labels.
        """
        with self.lock:
            known_encs = self.known_encodings
            known_names = self.known_names

        if not known_encs:
            # just display info text
            h, w = frame_bgr.shape[:2]
            cv2.putText(frame_bgr, "No encodings loaded. Hit /reload to load.",
                        (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            return frame_bgr

        # Convert to RGB for face_recognition
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Detect all faces (hog = CPU cepat; cnn = lebih akurat tapi butuh CUDA)
        boxes = face_recognition.face_locations(rgb, model="hog")
        encs = face_recognition.face_encodings(rgb, boxes)

        for (top, right, bottom, left), enc in zip(boxes, encs):
            # Compute distance to all known encodings
            distances = face_recognition.face_distance(known_encs, enc)
            if len(distances) == 0:
                name = "Unknown"
                best_dist = 1.0
            else:
                idx = int(np.argmin(distances))
                best_dist = float(distances[idx])
                name = known_names[idx] if best_dist <= TOLERANCE else "Unknown"

            # Draw
            cv2.rectangle(frame_bgr, (left, top), (right, bottom), (0, 255, 0) if name != "Unknown" else (0, 0, 255), 2)
            label = f"{name} ({best_dist:.2f})" if name != "Unknown" else f"Unknown ({best_dist:.2f})"
            cv2.rectangle(frame_bgr, (left, bottom - 22), (right, bottom), (0, 0, 0), -1)
            cv2.putText(frame_bgr, label, (left + 5, bottom - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, lineType=cv2.LINE_AA)
        return frame_bgr

recognizer = Recognizer()

# ===================== Flask App =====================
app = Flask(__name__)

INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Face Recognition FTL GYM</title>
  <style>
    :root {
      --bg-primary: #ffffff;
      --bg-secondary: #f8f9fa;
      --text-primary: #212529;
      --text-secondary: #6c757d;
      --border-color: #dee2e6;
      --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    }
    
    [data-theme="dark"] {
      --bg-primary: #1a1a1a;
      --bg-secondary: #2d2d2d;
      --text-primary: #ffffff;
      --text-secondary: #a0a0a0;
      --border-color: #404040;
      --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.2);
      --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -2px rgba(0, 0, 0, 0.2);
    }
    
    * { box-sizing: border-box; }
    
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0;
      padding: 0;
      background: var(--bg-primary);
      color: var(--text-primary);
      transition: background-color 0.3s ease, color 0.3s ease;
      min-height: 100vh;
    }
    
    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
    }
    
    .header {
      text-align: center;
      margin-bottom: 30px;
    }
    
    .header h1 {
      margin: 0 0 10px 0;
      font-size: 2.5rem;
      font-weight: 700;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    
    .controls {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 12px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    
    .btn {
      padding: 12px 20px;
      border: none;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s ease;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    
    .btn-primary {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
    }
    
    .btn-primary:hover {
      transform: translateY(-1px);
      box-shadow: var(--shadow-lg);
    }
    
    .btn-secondary {
      background: var(--bg-secondary);
      color: var(--text-primary);
      border: 1px solid var(--border-color);
    }
    
    .btn-secondary:hover {
      background: var(--border-color);
    }
    
    .btn-danger {
      background: #dc3545;
      color: white;
    }
    
    .btn-danger:hover {
      background: #c82333;
    }
    
    .theme-toggle {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      color: var(--text-primary);
      padding: 8px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 18px;
    }
    
    .status {
      text-align: center;
      margin: 20px 0;
      padding: 12px 20px;
      border-radius: 8px;
      font-weight: 500;
    }
    
    .status.success {
      background: #d4edda;
      color: #155724;
      border: 1px solid #c3e6cb;
    }
    
    .status.error {
      background: #f8d7da;
      color: #721c24;
      border: 1px solid #f5c6cb;
    }
    
    .status.info {
      background: #d1ecf1;
      color: #0c5460;
      border: 1px solid #bee5eb;
    }
    
    .camera-container {
      display: flex;
      justify-content: center;
      margin: 30px 0;
    }
    
    .camera-wrapper {
      position: relative;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: var(--shadow-lg);
      background: #000;
      width: 100%;
      max-width: 960px;
      aspect-ratio: 16/9;
    }
    
    .banner {
      position: absolute;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      background: linear-gradient(135deg, #10b981, #059669);
      color: white;
      padding: 15px 25px;
      border-radius: 12px;
      box-shadow: 0 10px 25px rgba(16, 185, 129, 0.3);
      z-index: 10;
      animation: slideDown 0.5s ease-out;
    }
    
    .banner.hidden {
      display: none;
    }
    
    .banner-content {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    
    .banner-icon {
      font-size: 24px;
    }
    
    .banner-text {
      display: flex;
      flex-direction: column;
    }
    
    .banner-title {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 2px;
    }
    
    .banner-name {
      font-size: 14px;
      opacity: 0.9;
    }
    
    @keyframes slideDown {
      from {
        opacity: 0;
        transform: translateX(-50%) translateY(-20px);
      }
      to {
        opacity: 1;
        transform: translateX(-50%) translateY(0);
      }
    }
    
    /* Fullscreen styles */
    .camera-container:fullscreen {
      background: #000;
      display: flex;
      justify-content: center;
      align-items: center;
      width: 100vw;
      height: 100vh;
    }
    
    .camera-container:fullscreen .camera-wrapper {
      width: 100vw;
      height: 100vh;
      max-width: none;
      max-height: none;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .camera-container:fullscreen #video,
    .camera-container:fullscreen #canvas {
      width: 100vw !important;
      height: 100vh !important;
      object-fit: cover;
      max-width: none;
      max-height: none;
    }
    
    .camera-container:fullscreen .banner {
      position: absolute;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 10000;
    }
    
    /* Fallback CSS fullscreen */
    .fullscreen-mode {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: #000;
      z-index: 9999;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .fullscreen-mode .camera-container {
      margin: 0;
      width: 100%;
      height: 100%;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .fullscreen-mode .camera-wrapper {
      width: 100vw;
      height: 100vh;
      max-width: none;
      max-height: none;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .fullscreen-mode #video,
    .fullscreen-mode #canvas {
      width: 100vw !important;
      height: 100vh !important;
      object-fit: cover;
      max-width: none;
      max-height: none;
    }
    
    .fullscreen-mode .controls,
    .fullscreen-mode .header,
    .fullscreen-mode #status {
      display: none;
    }
    
    .fullscreen-mode .banner {
      position: absolute;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 10000;
    }
    
    .fullscreen-exit {
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 10001;
      background: rgba(0, 0, 0, 0.7);
      color: white;
      border: none;
      border-radius: 8px;
      padding: 12px 20px;
      font-size: 14px;
      cursor: pointer;
      display: none;
    }
    
    .fullscreen-mode .fullscreen-exit {
      display: block;
    }
    
    /* Webkit fullscreen support */
    .camera-container:-webkit-full-screen {
      background: #000;
      display: flex;
      justify-content: center;
      align-items: center;
      width: 100vw;
      height: 100vh;
    }
    
    .camera-container:-webkit-full-screen .camera-wrapper {
      width: 100vw;
      height: 100vh;
      max-width: none;
      max-height: none;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .camera-container:-webkit-full-screen #video,
    .camera-container:-webkit-full-screen #canvas {
      width: 100vw !important;
      height: 100vh !important;
      object-fit: cover;
      max-width: none;
      max-height: none;
    }
    
    .camera-container:-webkit-full-screen .banner {
      position: absolute;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 10000;
    }
    
    #video {
      display: none;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    
    #canvas {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    
    .info-panel {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 20px;
      margin-top: 30px;
      text-align: center;
    }
    
    .info-panel h3 {
      margin: 0 0 15px 0;
      color: var(--text-primary);
    }
    
    .info-panel p {
      margin: 0;
      color: var(--text-secondary);
      line-height: 1.6;
    }
    
    .door-selector {
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 8px 12px;
    }
    
    .door-selector label {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      margin: 0;
    }
    
    .door-selector select {
      background: var(--bg-primary);
      border: 1px solid var(--border-color);
      border-radius: 4px;
      padding: 6px 8px;
      font-size: 14px;
      color: var(--text-primary);
      cursor: pointer;
      min-width: 200px;
    }
    
    .door-selector select:focus {
      outline: none;
      border-color: var(--accent-color);
      box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2);
    }
    
    @media (max-width: 1024px) {
      .container { padding: 15px; }
      .header h1 { font-size: 2rem; }
      .camera-wrapper { 
        max-width: 100%;
        aspect-ratio: 4/3;
      }
      .controls { flex-direction: column; gap: 8px; }
    }
    
    @media (max-width: 768px) {
      .container { padding: 10px; }
      .header h1 { font-size: 1.5rem; }
      .camera-wrapper { 
        max-width: 100%;
        aspect-ratio: 4/3;
        border-radius: 12px;
      }
      .controls { 
        flex-direction: column; 
        gap: 8px; 
        margin-bottom: 15px;
      }
      .door-selector {
        flex-direction: column;
        align-items: flex-start;
        gap: 5px;
      }
      .door-selector select {
        min-width: 100%;
      }
    }
    
    @media (max-width: 480px) {
      .container { padding: 5px; }
      .header h1 { font-size: 1.2rem; }
      .camera-wrapper { 
        aspect-ratio: 3/4;
        border-radius: 8px;
      }
      .banner {
        top: 10px;
        padding: 10px 15px;
        font-size: 14px;
      }
      .banner-title {
        font-size: 16px;
      }
      .banner-name {
        font-size: 12px;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Face Recognition FTL GYM</h1>
      <p style="color: var(--text-secondary); margin: 0;">Powered by Dlib & face_recognition</p>
  </div>
    
    <div class="controls">
      <button class="btn btn-primary" onclick="startCamera()">
        <span>📹</span> Start Camera
      </button>
      <button class="btn btn-danger" onclick="stopCamera()">
        <span>⏹️</span> Stop Camera
      </button>
      
      <div class="door-selector">
        <label for="doorSelect">Cabang:</label>
        <select id="doorSelect" onchange="updateDoorId()">
          <option value="">Pilih Cabang</option>
          <option value="19456">FTL - Center / Door 1</option>
          <option value="19418">FTL - Center / Reception - CT</option>
          <option value="19429">FTL - Benhil / Reception - BH</option>
          <option value="4">FTL - Tebet / Reception - TB</option>
        </select>
      </div>
      
      <button class="btn btn-secondary" onclick="toggleFullscreen()" title="Toggle Fullscreen">
        <span id="fullscreen-icon">⛶</span>
        <span id="fullscreen-text">Fullscreen</span>
      </button>
      
      <button class="theme-toggle" onclick="toggleTheme()" title="Toggle Dark Mode">
        <span id="theme-icon">🌙</span>
      </button>
    </div>
    
    <div id="status" class="status info">Click "Start Camera" to begin face recognition</div>
    
    <div class="camera-container">
      <div class="camera-wrapper">
        <video id="video" autoplay muted></video>
        <canvas id="canvas" width="960" height="720"></canvas>
        <div id="banner" class="banner hidden">
          <div class="banner-content">
            <div class="banner-icon">✅</div>
            <div class="banner-text">
              <div class="banner-title">Access Granted</div>
              <div class="banner-name">Nama: <span id="banner-name"></span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <button class="fullscreen-exit" onclick="exitFullscreen()">
      <span>✕</span> Exit Fullscreen
    </button>
    
  </div>

  <script>
    // Dark mode functionality
    function toggleTheme() {
      const body = document.body;
      const themeIcon = document.getElementById('theme-icon');
      const currentTheme = body.getAttribute('data-theme');
      
      if (currentTheme === 'dark') {
        body.removeAttribute('data-theme');
        themeIcon.textContent = '🌙';
        localStorage.setItem('theme', 'light');
      } else {
        body.setAttribute('data-theme', 'dark');
        themeIcon.textContent = '☀️';
        localStorage.setItem('theme', 'dark');
      }
    }
    
    // Door ID functionality
    function updateDoorId() {
      const doorSelect = document.getElementById('doorSelect');
      const selectedDoorId = doorSelect.value;
      
      // If no door selected, don't send to server
      if (!selectedDoorId) {
        console.log('[DOOR] No door selected');
        return;
      }
      
      // Send door ID to server
      fetch('/update_door_id', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ door_id: selectedDoorId })
      })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          console.log(`[DOOR] Door ID updated to: ${selectedDoorId}`);
          updateStatus(`Cabang dipilih: ${doorSelect.options[doorSelect.selectedIndex].text}`, 'success');
        } else {
          console.error('[DOOR] Failed to update door ID:', data.error);
          updateStatus(`Failed to update door ID: ${data.error}`, 'error');
        }
      })
      .catch(error => {
        console.error('[DOOR] Error updating door ID:', error);
        updateStatus(`Error updating door ID: ${error}`, 'error');
      });
    }
    
    // Fullscreen functionality
    function toggleFullscreen() {
      if (document.fullscreenElement) {
        exitFullscreen();
      } else {
        enterFullscreen();
      }
    }
    
    function enterFullscreen() {
      const cameraContainer = document.querySelector('.camera-container');
      const fullscreenIcon = document.getElementById('fullscreen-icon');
      const fullscreenText = document.getElementById('fullscreen-text');
      
      if (cameraContainer.requestFullscreen) {
        cameraContainer.requestFullscreen().then(() => {
          cameraContainer.classList.add('fullscreen-mode');
          fullscreenIcon.textContent = '⛶';
          fullscreenText.textContent = 'Exit';
          resizeCanvas();
        }).catch(err => {
          console.error('Error entering fullscreen:', err);
          // Fallback to CSS fullscreen
          document.querySelector('.container').classList.add('fullscreen-mode');
          fullscreenIcon.textContent = '⛶';
          fullscreenText.textContent = 'Exit';
          resizeCanvas();
        });
      } else {
        // Fallback for browsers that don't support Fullscreen API
        document.querySelector('.container').classList.add('fullscreen-mode');
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Exit';
        resizeCanvas();
      }
    }
    
    function exitFullscreen() {
      const fullscreenIcon = document.getElementById('fullscreen-icon');
      const fullscreenText = document.getElementById('fullscreen-text');
      
      if (document.fullscreenElement) {
        document.exitFullscreen().then(() => {
          document.querySelector('.camera-container').classList.remove('fullscreen-mode');
          fullscreenIcon.textContent = '⛶';
          fullscreenText.textContent = 'Fullscreen';
          resizeCanvas();
        }).catch(err => {
          console.error('Error exiting fullscreen:', err);
        });
      } else {
        // Fallback for CSS fullscreen
        document.querySelector('.container').classList.remove('fullscreen-mode');
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Fullscreen';
        resizeCanvas();
      }
    }
    
    // Handle ESC key to exit fullscreen
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && document.fullscreenElement) {
        exitFullscreen();
      }
    });
    
    // Handle fullscreen change events
    document.addEventListener('fullscreenchange', function() {
      const cameraContainer = document.querySelector('.camera-container');
      const fullscreenIcon = document.getElementById('fullscreen-icon');
      const fullscreenText = document.getElementById('fullscreen-text');
      
      if (document.fullscreenElement) {
        cameraContainer.classList.add('fullscreen-mode');
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Exit';
      } else {
        cameraContainer.classList.remove('fullscreen-mode');
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Fullscreen';
      }
      resizeCanvas();
    });
    
    // Handle window resize for responsiveness
    window.addEventListener('resize', function() {
      resizeCanvas();
    });
    
    // Handle orientation change on mobile
    window.addEventListener('orientationchange', function() {
      setTimeout(resizeCanvas, 100);
    });
    
    // Load saved theme on page load
    document.addEventListener('DOMContentLoaded', function() {
      const savedTheme = localStorage.getItem('theme');
      const themeIcon = document.getElementById('theme-icon');
      
      if (savedTheme === 'dark') {
        document.body.setAttribute('data-theme', 'dark');
        themeIcon.textContent = '☀️';
      }
      
      // Reset door selection to default on page load
      const doorSelect = document.getElementById('doorSelect');
      if (doorSelect) {
        doorSelect.value = '';
      }
    });

    // Face recognition functionality
    let stream = null;
    let video = document.getElementById('video');
    let canvas = document.getElementById('canvas');
    let ctx = canvas.getContext('2d');
    let status = document.getElementById('status');
    let isProcessing = false;
    let inFlight = false;
    let lastFaces = [];
    let lastFacesTime = 0;
    const FACES_TTL_MS = 1200;
    const SMOOTHING_ALPHA = 0.5;
    const workCanvas = document.createElement('canvas');
    const workCtx = workCanvas.getContext('2d');

    function updateStatus(message, type = 'info') {
      status.textContent = message;
      status.className = 'status ' + type;
    }

    async function startCamera() {
      // Check if door ID is selected
      const doorSelect = document.getElementById('doorSelect');
      if (!doorSelect.value) {
        alert('Pilih Cabang terlebih dahulu!');
        updateStatus('Silakan pilih cabang sebelum memulai kamera', 'error');
        return;
      }
      
      try {
        updateStatus('Requesting camera access...', 'info');
        stream = await navigator.mediaDevices.getUserMedia({ 
          video: { 
            width: 960, 
            height: 720,
            facingMode: 'user'
          } 
        });
        video.srcObject = stream;
        updateStatus('Camera started successfully!', 'success');
        startProcessing();
      } catch (error) {
        updateStatus('Camera access denied or not available: ' + error.message, 'error');
      }
    }

    function stopCamera() {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
        video.srcObject = null;
        updateStatus('Camera stopped', 'info');
      }
    }

    function startProcessing() {
      if (isProcessing) return;
      isProcessing = true;
      requestAnimationFrame(drawDisplay);
      processFrame();
    }

    let lastProcessTime = 0;
    const PROCESS_INTERVAL = 60; // recognition cadence

    function processFrame() {
      if (!stream || !video.videoWidth) {
        if (isProcessing) {
          setTimeout(processFrame, 200);
        }
        return;
      }

      const now = Date.now();
      if (now - lastProcessTime < PROCESS_INTERVAL) {
        if (isProcessing) {
          setTimeout(processFrame, 100);
        }
        return;
      }
      lastProcessTime = now;

      // Downscale for recognition to reduce bandwidth/CPU
      const targetW = 640;
      const scale = targetW / video.videoWidth;
      const targetH = Math.round(video.videoHeight * scale);
      workCanvas.width = targetW;
      workCanvas.height = targetH;
      workCtx.drawImage(video, 0, 0, targetW, targetH);

      if (inFlight) {
        if (isProcessing) setTimeout(processFrame, 50);
        return;
      }
      inFlight = true;

      // Send frame to server for face recognition
      workCanvas.toBlob(function(blob) {
        const formData = new FormData();
        formData.append('frame', blob);
        
        fetch('/recognize', {
          method: 'POST',
          body: formData
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            updateFaces(data.faces, scale);
            updateBanner(data.banner);
          } else {
            console.error('Recognition failed:', data.error);
          }
        })
        .catch(error => {
          console.error('Recognition error:', error);
        })
        .finally(() => { inFlight = false; });
      }, 'image/jpeg', 0.6);

      if (isProcessing) {
        setTimeout(processFrame, 200);
      }
    }

    function updateFaces(newFaces, scale) {
      const upscaled = newFaces.map(f => ({
        x: Math.round(f.x / scale),
        y: Math.round(f.y / scale),
        width: Math.round(f.width / scale),
        height: Math.round(f.height / scale),
        name: f.name,
        confidence: f.confidence
      }));
      if (lastFaces.length === 0) {
        lastFaces = upscaled;
      } else {
        lastFaces = smoothFaces(lastFaces, upscaled);
      }
      lastFacesTime = Date.now();
    }
    
    function updateBanner(bannerInfo) {
      const banner = document.getElementById('banner');
      const bannerName = document.getElementById('banner-name');
      
      console.log('[BANNER] Received banner info:', bannerInfo);
      
      if (bannerInfo && bannerInfo.show) {
        console.log('[BANNER] Showing banner for:', bannerInfo.name);
        bannerName.textContent = bannerInfo.name;
        banner.classList.remove('hidden');
        
        // Auto hide after 2 seconds
        setTimeout(() => {
          console.log('[BANNER] Hiding banner');
          banner.classList.add('hidden');
        }, 2000);
      } else {
        banner.classList.add('hidden');
      }
    }

    function smoothFaces(prev, curr) {
      const result = [];
      const used = new Array(curr.length).fill(false);
      for (let p of prev) {
        let bestIdx = -1;
        let bestIou = 0;
        for (let i = 0; i < curr.length; i++) {
          if (used[i]) continue;
          const iou = boxIoU(p, curr[i]);
          if (iou > bestIou) { bestIou = iou; bestIdx = i; }
        }
        if (bestIdx >= 0 && bestIou > 0.1) {
          const c = curr[bestIdx];
          used[bestIdx] = true;
          result.push({
            x: Math.round(p.x * (1-SMOOTHING_ALPHA) + c.x * SMOOTHING_ALPHA),
            y: Math.round(p.y * (1-SMOOTHING_ALPHA) + c.y * SMOOTHING_ALPHA),
            width: Math.round(p.width * (1-SMOOTHING_ALPHA) + c.width * SMOOTHING_ALPHA),
            height: Math.round(p.height * (1-SMOOTHING_ALPHA) + c.height * SMOOTHING_ALPHA),
            name: c.name || p.name,
            confidence: c.confidence
          });
        }
      }
      for (let i = 0; i < curr.length; i++) if (!used[i]) result.push(curr[i]);
      return result;
    }

    function boxIoU(a, b) {
      const x1 = Math.max(a.x, b.x);
      const y1 = Math.max(a.y, b.y);
      const x2 = Math.min(a.x + a.width, b.x + b.width);
      const y2 = Math.min(a.y + a.height, b.y + b.height);
      const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
      const areaA = a.width * a.height;
      const areaB = b.width * b.height;
      const union = areaA + areaB - inter;
      return union > 0 ? inter / union : 0;
    }

    function resizeCanvas() {
      if (!video.videoWidth || !video.videoHeight) return;
      
      const container = canvas.parentElement;
      const containerWidth = container.clientWidth;
      const containerHeight = container.clientHeight;
      const aspectRatio = video.videoWidth / video.videoHeight;
      
      // For fullscreen mode, use viewport dimensions
      if (container.classList.contains('fullscreen-mode') || document.fullscreenElement) {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        canvas.style.width = '100vw';
        canvas.style.height = '100vh';
        return;
      }
      
      // For normal mode, fit within container
      let canvasWidth = containerWidth;
      let canvasHeight = containerWidth / aspectRatio;
      
      // If height exceeds container, scale down
      if (canvasHeight > containerHeight) {
        canvasHeight = containerHeight;
        canvasWidth = containerHeight * aspectRatio;
      }
      
      canvas.width = canvasWidth;
      canvas.height = canvasHeight;
      
      // Update CSS size to match canvas dimensions
      canvas.style.width = canvasWidth + 'px';
      canvas.style.height = canvasHeight + 'px';
    }

    function drawDisplay() {
      if (!isProcessing) return;
      
      // Resize canvas to match video aspect ratio
      resizeCanvas();
      
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const now = Date.now();
      const showFaces = (now - lastFacesTime) < FACES_TTL_MS ? lastFaces : [];
      
      // Calculate scaling factors based on actual video dimensions
      const sx = video.videoWidth ? canvas.width / video.videoWidth : 1;
      const sy = video.videoHeight ? canvas.height / video.videoHeight : 1;
      
      for (const face of showFaces) {
        const { x, y, width, height, name, confidence, cooldown, cooldown_remaining } = face;
        const dx = Math.round(x * sx);
        const dy = Math.round(y * sy);
        const dw = Math.round(width * sx);
        const dh = Math.round(height * sy);
        
        // Different colors for different states
        let color = '#ff0000'; // Default red for unknown
        if (cooldown) {
          color = '#ffa500'; // Orange for cooldown
        } else if (name !== 'Unknown') {
          color = '#00ff00'; // Green for recognized
        }
        
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(dx, dy, dw, dh);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect(dx, dy + dh - 25, dw, 25);
        ctx.fillStyle = '#ffffff';
        ctx.font = '14px Arial';
        
        // Display different text based on state
        if (cooldown) {
          ctx.fillText(`⏳ Cooldown: ${cooldown_remaining.toFixed(1)}s`, dx + 5, dy + dh - 8);
        } else {
          ctx.fillText(`${name} (${confidence.toFixed(2)})`, dx + 5, dy + dh - 8);
        }
      }
      requestAnimationFrame(drawDisplay);
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', stopCamera);
  </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(INDEX_HTML, tol=TOLERANCE)

@app.route('/update_door_id', methods=['POST'])
def update_door_id():
    try:
        from flask import request
        data = request.get_json()
        door_id = data.get('door_id')
        
        if not door_id:
            return {"success": False, "error": "Door ID is required"}
        
        # Update global door ID
        global GYM_DOOR_ID
        GYM_DOOR_ID = door_id
        
        print(f"[DOOR] Door ID updated to: {door_id}")
        return {"success": True, "door_id": door_id}
        
    except Exception as e:
        print(f"[DOOR] Error updating door ID: {e}")
        return {"success": False, "error": str(e)}

@app.route("/recognize", methods=["POST"])
def recognize():
    try:
        from flask import request
        
        if 'frame' not in request.files:
            return {"success": False, "error": "No frame provided"}
        
        file = request.files['frame']
        if file.filename == '':
            return {"success": False, "error": "No file selected"}
        
        # Read image data
        image_data = file.read()
        nparr = np.frombuffer(image_data, np.uint8)
        frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame_bgr is None:
            return {"success": False, "error": "Invalid image"}
        
        # Convert to RGB for face detection
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        
        # Detect faces and get recognition results
        with recognizer.lock:
            known_encs = recognizer.known_encodings
            known_names = recognizer.known_names
            known_ids = recognizer.known_ids
        
        
        if not known_encs:
            return {"success": True, "faces": [], "debug": "No known encodings loaded"}
        
        # Detect faces
        boxes = face_recognition.face_locations(rgb, model="hog")
        
        if not boxes:
            return {"success": True, "faces": [], "debug": "No faces detected"}
        
        # Sort faces by size (largest first) and take only the first one
        face_sizes = [(i, (box[2] - box[0]) * (box[3] - box[1])) for i, box in enumerate(boxes)]
        face_sizes.sort(key=lambda x: x[1], reverse=True)  # Sort by area, largest first
        
        # Take only the largest face (most front)
        largest_face_idx = face_sizes[0][0]
        largest_box = boxes[largest_face_idx]
        
        # Generate encoding only for the largest face
        encs = face_recognition.face_encodings(rgb, [largest_box])
        
        if not encs:
            return {"success": True, "faces": [], "debug": "No face encoding generated"}
        
        faces = []
        # Process only the largest face
        (top, right, bottom, left) = largest_box
        enc = encs[0]  # Only one encoding for the largest face
        
        distances = face_recognition.face_distance(known_encs, enc)
        if len(distances) == 0:
            name = "Unknown"
            confidence = 1.0
            member_id = None
        else:
            idx = int(np.argmin(distances))
            confidence = float(distances[idx])
            name = known_names[idx] if confidence <= TOLERANCE else "Unknown"
            member_id = known_ids[idx] if confidence <= TOLERANCE else None
        
        # Process gym gate if member is recognized
        if member_id and confidence <= TOLERANCE:
            # Check cooldown first
            if recognizer.is_in_cooldown():
                cooldown_remaining = recognizer.get_cooldown_remaining()
                print(f"[GYM] ⏳ Cooldown active: {cooldown_remaining:.1f}s remaining")
                # Add cooldown info to face data
                faces.append({
                    "x": int(left),
                    "y": int(top),
                    "width": int(right - left),
                    "height": int(bottom - top),
                    "name": f"Cooldown: {cooldown_remaining:.1f}s",
                    "confidence": confidence,
                    "cooldown": True,
                    "cooldown_remaining": cooldown_remaining
                })
            else:
                # Get gym_member_id for API call
                gym_member_id = recognizer.gym_member_id_mapping.get(member_id)
                if gym_member_id:
                    gym_result = process_member_detection(gym_member_id, name)
                    if gym_result["success"]:
                        print(f"[GYM] ✅ {gym_result['message']}")
                        # Mark successful login to start cooldown
                        recognizer.set_successful_login(name)
                    else:
                        print(f"[GYM] ❌ {gym_result['error']}")
                else:
                    print(f"[GYM] ❌ No gym_member_id found for member_id={member_id}")
                
                # Add normal face data (not in cooldown)
                faces.append({
                    "x": int(left),
                    "y": int(top),
                    "width": int(right - left),
                    "height": int(bottom - top),
                    "name": name,
                    "confidence": confidence,
                    "member_id": member_id
                })
        else:
            # Add face data for unrecognized faces
            faces.append({
                "x": int(left),
                "y": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
                "name": name,
                "confidence": confidence,
                "member_id": member_id
            })
        
        # Add banner info if there was a recent successful login
        banner_info = None
        if recognizer.last_successful_member:
            # Show banner for 2 seconds after successful login
            time_since_login = time.time() - recognizer.last_successful_login
            if time_since_login < 2.0:  # Show banner for 2 seconds
                banner_info = {
                    "show": True,
                    "message": f"Access Granted",
                    "name": recognizer.last_successful_member
                }
                print(f"[BANNER] Showing banner for {recognizer.last_successful_member} ({time_since_login:.1f}s ago)")
        
        return {
            "success": True, 
            "faces": faces, 
            "banner": banner_info,
            "debug": f"Processed {len(faces)} faces"
        }
        
    except Exception as e:
        print(f"[RECOG] Error: {e}")
        return {"success": False, "error": str(e)}

@app.route("/reload")
def reload_route():
    threading.Thread(target=recognizer.reload, daemon=True).start()
    return "Reload encodings dipicu. Tunggu 1-3 detik lalu refresh stream."

@app.route("/health")
def health():
    with recognizer.lock:
        n = len(recognizer.known_encodings)
        last = recognizer.last_reload
    return {
        "ok": True,
        "encodings": n,
        "last_reload_epoch": last,
        "tolerance": TOLERANCE
    }

# ===================== Main =====================
if __name__ == "__main__":
    # Initial load
    recognizer.reload()
    # Jalankan Flask
    # Akses di: http://127.0.0.1:5000/
    app.run(host="0.0.0.0", port=8001, debug=True, threaded=True)
