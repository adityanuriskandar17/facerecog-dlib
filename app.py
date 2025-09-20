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
    rows: List[Tuple[int, str, str, str]] = []
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

    latest_per_member: "OrderedDict[int, Tuple[int,str,str]]" = OrderedDict()
    for member_id, first_name, full_url, created_at in rows:
        if member_id not in latest_per_member:
            latest_per_member[member_id] = (member_id, first_name, full_url)
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

def build_known_encodings() -> Tuple[List[np.ndarray], List[str], List[int]]:
    """
    Return (encodings, names, member_ids)
    - 1 encoding per member (pakai face pertama yang terdeteksi di fotonya)
    """
    sources = fetch_member_images()
    encodings: List[np.ndarray] = []
    names: List[str] = []
    member_ids: List[int] = []
    skipped: List[Tuple[int, str]] = []

    print(f"[ENC] Mulai load {len(sources)} member image(s)")
    for member_id, first_name, full_url in sources:
        try:
            img = url_to_rgb_array(full_url)
            boxes = face_recognition.face_locations(img, model="hog")  # cepat; bisa 'cnn' jika ada GPU dlib yang siap
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
            encodings.append(encoding[0])
            names.append(first_name.strip() or f"Member_{member_id}")
            member_ids.append(member_id)
            print(f"[ENC] OK member_id={member_id} name={names[-1]}")
        except Exception as e:
            print(f"[ENC] Error for member_id={member_id}: {e}")
            skipped.append((member_id, "error"))

    print(f"[ENC] Selesai. OK={len(encodings)} Skip={len(skipped)}")
    return encodings, names, member_ids

# ===================== Video / Recognition =====================
class Recognizer:
    def __init__(self):
        self.known_encodings: List[np.ndarray] = []
        self.known_names: List[str] = []
        self.known_ids: List[int] = []
        self.lock = threading.Lock()
        self.last_reload = 0

    def reload(self):
        with self.lock:
            self.known_encodings, self.known_names, self.known_ids = build_known_encodings()
            self.last_reload = time.time()

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
  <title>Live Face Recognition (dlib)</title>
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
    }
    
    #video {
      display: none;
      width: 100%;
      height: auto;
      max-width: 960px;
      aspect-ratio: 4/3;
    }
    
    #canvas {
      display: block;
      width: 100%;
      height: auto;
      max-width: 960px;
      aspect-ratio: 4/3;
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
    
    .tolerance-display {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 8px 12px;
      font-family: 'Monaco', 'Menlo', monospace;
      font-size: 14px;
      color: var(--text-primary);
    }
    
    @media (max-width: 1024px) {
      .container { padding: 15px; }
      .header h1 { font-size: 2rem; }
      #video, #canvas { max-width: 100%; }
      .controls { flex-direction: column; gap: 8px; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Live Face Recognition</h1>
      <p style="color: var(--text-secondary); margin: 0;">Powered by Dlib & face_recognition</p>
    </div>
    
    <div class="controls">
      <button class="btn btn-primary" onclick="startCamera()">
        <span>📹</span> Start Camera
      </button>
      <button class="btn btn-danger" onclick="stopCamera()">
        <span>⏹️</span> Stop Camera
      </button>
      <a class="btn btn-secondary" href="/reload">
        <span>🔄</span> Reload Encodings
      </a>
      <a class="btn btn-secondary" href="/health">
        <span>💚</span> Health Check
      </a>
      <div class="tolerance-display">
        Tolerance: {{ tol }}
      </div>
      <button class="theme-toggle" onclick="toggleTheme()" title="Toggle Dark Mode">
        <span id="theme-icon">🌙</span>
      </button>
    </div>
    
    <div id="status" class="status info">Click "Start Camera" to begin face recognition</div>
    
    <div class="camera-container">
      <div class="camera-wrapper">
        <video id="video" autoplay muted></video>
        <canvas id="canvas" width="960" height="720"></canvas>
      </div>
    </div>
    
    <div class="info-panel">
      <h3>💡 Tips</h3>
      <p>
        To adjust recognition accuracy, modify the <code>TOLERANCE</code> value in the code 
        (0.35 for stricter, 0.55 for looser) and click <strong>Reload Encodings</strong>.
      </p>
    </div>
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
    
    // Load saved theme on page load
    document.addEventListener('DOMContentLoaded', function() {
      const savedTheme = localStorage.getItem('theme');
      const themeIcon = document.getElementById('theme-icon');
      
      if (savedTheme === 'dark') {
        document.body.setAttribute('data-theme', 'dark');
        themeIcon.textContent = '☀️';
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
      
      const containerWidth = canvas.parentElement.clientWidth;
      const maxWidth = Math.min(960, containerWidth);
      const aspectRatio = video.videoWidth / video.videoHeight;
      
      canvas.width = maxWidth;
      canvas.height = maxWidth / aspectRatio;
      
      // Update CSS size to match canvas dimensions
      canvas.style.width = maxWidth + 'px';
      canvas.style.height = (maxWidth / aspectRatio) + 'px';
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
        const { x, y, width, height, name, confidence } = face;
        const dx = Math.round(x * sx);
        const dy = Math.round(y * sy);
        const dw = Math.round(width * sx);
        const dh = Math.round(height * sy);
        const color = name === 'Unknown' ? '#ff0000' : '#00ff00';
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(dx, dy, dw, dh);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect(dx, dy + dh - 25, dw, 25);
        ctx.fillStyle = '#ffffff';
        ctx.font = '14px Arial';
        ctx.fillText(`${name} (${confidence.toFixed(2)})`, dx + 5, dy + dh - 8);
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
        
        print(f"[RECOG] Processing frame, known faces: {len(known_encs)}")
        
        if not known_encs:
            return {"success": True, "faces": [], "debug": "No known encodings loaded"}
        
        # Detect faces
        boxes = face_recognition.face_locations(rgb, model="hog")
        print(f"[RECOG] Found {len(boxes)} faces")
        
        if not boxes:
            return {"success": True, "faces": [], "debug": "No faces detected"}
        
        encs = face_recognition.face_encodings(rgb, boxes)
        print(f"[RECOG] Generated {len(encs)} encodings")
        
        faces = []
        for i, ((top, right, bottom, left), enc) in enumerate(zip(boxes, encs)):
            distances = face_recognition.face_distance(known_encs, enc)
            if len(distances) == 0:
                name = "Unknown"
                confidence = 1.0
            else:
                idx = int(np.argmin(distances))
                confidence = float(distances[idx])
                name = known_names[idx] if confidence <= TOLERANCE else "Unknown"
                print(f"[RECOG] Face {i}: {name} (confidence: {confidence:.3f}, tolerance: {TOLERANCE})")
            
            faces.append({
                "x": int(left),
                "y": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
                "name": name,
                "confidence": confidence
            })
        
        return {"success": True, "faces": faces, "debug": f"Processed {len(faces)} faces"}
        
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
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
