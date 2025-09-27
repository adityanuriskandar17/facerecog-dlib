from flask import Blueprint, render_template, redirect, url_for, request, session, render_template_string
from .auth import require_login, fetch_member_profile

# Create main blueprint
main_bp = Blueprint('main', __name__)

# Import the INDEX_HTML template from app_old.py
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
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
    
    .btn-success {
      background: #28a745;
      color: white;
    }
    
    .btn-success:hover {
      background: #218838;
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
      aspect-ratio: 4/3;
      min-height: 300px;
      max-height: 80vh;
    }
    
    .cooldown-display {
      position: absolute;
      top: 20px;
      right: 20px;
      background: linear-gradient(135deg, #ff6b35, #f7931e);
      color: white;
      padding: 12px 20px;
      border-radius: 12px;
      box-shadow: 0 8px 25px rgba(255, 107, 53, 0.3);
      z-index: 10;
      animation: pulse 1s ease-in-out infinite;
    }
    
    .cooldown-display.hidden {
      display: none;
    }
    
    .popup-notification {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      z-index: 10000;
      padding: 30px 40px;
      border-radius: 20px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
      text-align: center;
      font-weight: 700;
      font-size: 24px;
      color: white;
      animation: popupSlideIn 0.5s ease-out;
      min-width: 300px;
      max-width: 500px;
    }
    
    .popup-notification.granted {
      background: linear-gradient(135deg, #10b981, #059669);
      border: 3px solid #34d399;
    }
    
    .popup-notification.denied {
      background: linear-gradient(135deg, #ef4444, #dc2626);
      border: 3px solid #f87171;
    }
    
    .popup-notification.info {
      background: linear-gradient(135deg, #f59e0b, #d97706);
      border: 3px solid #fbbf24;
      color: #1f2937;
    }
    
    .popup-notification.hidden {
      display: none;
    }
    
    .popup-icon {
      font-size: 48px;
      margin-bottom: 15px;
      display: block;
    }
    
    .popup-title {
      font-size: 28px;
      margin-bottom: 10px;
      font-weight: 800;
    }
    
    .popup-message {
      font-size: 16px;
      opacity: 0.9;
      font-weight: 500;
      line-height: 1.4;
    }
    
    .popup-member-name {
      font-size: 20px;
      margin: 10px 0;
      font-weight: 700;
    }
    
    .popup-member-id {
      font-size: 14px;
      opacity: 0.8;
      margin-top: 5px;
    }
    
    @keyframes popupSlideIn {
      from {
        opacity: 0;
        transform: translate(-50%, -50%) scale(0.8);
      }
      to {
        opacity: 1;
        transform: translate(-50%, -50%) scale(1);
      }
    }
    
    @keyframes pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.05); }
    }
    
    #video {
      display: none;
      width: 100%;
      height: 100%;
      object-fit: cover;
      position: absolute;
      top: 0;
      left: 0;
    }
    
    #canvas {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      background: #000;
      max-width: 100%;
      max-height: 100%;
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
    
    @media (max-width: 1024px) {
      .container { padding: 15px; }
      .header h1 { font-size: 2rem; }
      .camera-wrapper { 
        max-width: 100%;
        aspect-ratio: 4/3;
        max-height: 70vh;
      }
      .controls { flex-direction: column; gap: 8px; }
    }
    
    @media (max-width: 768px) {
      .container { padding: 10px; }
      .header h1 { font-size: 1.5rem; }
      .camera-wrapper { 
        max-width: 100%;
        aspect-ratio: 3/4;
        border-radius: 12px;
        max-height: 70vh;
        min-height: 300px;
      }
      .controls { 
        flex-direction: column; 
        gap: 8px; 
        margin-bottom: 15px;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Face Recognition FTL GYM</h1>
      <p style="color: var(--text-secondary); margin: 0;">Powered by Horizon</p>
    </div>
    
    <div class="controls">
      <button class="btn btn-success" onclick="window.location.href='/login'">
        <span>🔐</span> Login
      </button>
      <button class="btn btn-primary" onclick="startCamera()">
        <span>📹</span> Start Camera
      </button>
      <button class="btn btn-danger" onclick="stopCamera()">
        <span>⏹️</span> Stop Camera
      </button>
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
        <video id="video" autoplay muted playsinline></video>
        <canvas id="canvas" width="960" height="720"></canvas>
        <div id="cooldown-display" class="cooldown-display hidden">
          <div class="cooldown-content">
            <div class="cooldown-icon">⏳</div>
            <div class="cooldown-text">
              <div class="cooldown-title">Cooldown</div>
              <div class="cooldown-time"><span id="cooldown-time">0.0</span>s</div>
            </div>
          </div>
        </div>
        <div id="popup-notification" class="popup-notification hidden">
          <div class="popup-icon" id="popup-icon">✅</div>
          <div class="popup-title" id="popup-title">ACCESS GRANTED</div>
          <div class="popup-member-name" id="popup-member-name">Member Name</div>
          <div class="popup-member-id" id="popup-member-id">Member #123456</div>
          <div class="popup-message" id="popup-message">Welcome to FTL Gym!</div>
        </div>
      </div>
    </div>
    
    <div class="info-panel">
      <h3>Face Recognition System</h3>
      <p>This system uses advanced facial recognition technology to provide secure access control for FTL Gym members. Click "Login" to access member features, or use the camera for guest recognition.</p>
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
    
    // Fullscreen functionality
    function toggleFullscreen() {
      const cameraContainer = document.querySelector('.camera-container');
      const fullscreenIcon = document.getElementById('fullscreen-icon');
      const fullscreenText = document.getElementById('fullscreen-text');
      
      if (document.fullscreenElement) {
        document.exitFullscreen();
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Fullscreen';
      } else {
        if (cameraContainer.requestFullscreen) {
          cameraContainer.requestFullscreen();
          fullscreenIcon.textContent = '⛶';
          fullscreenText.textContent = 'Exit';
        }
      }
    }
    
    // Generate unique device ID
    function getDeviceId() {
      let deviceId = localStorage.getItem('deviceId');
      if (!deviceId) {
        deviceId = 'device_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('deviceId', deviceId);
      }
      return deviceId;
    }

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
    
    // Simple popup control
    let currentPopupTimeout = null;

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
        video.load();
        
        // Wait for video to be ready
        video.onloadedmetadata = function() {
          console.log('[CAMERA] Video metadata loaded');
          updateStatus('Camera started successfully!', 'success');
          
          // Start processing
          setTimeout(() => {
            video.play().then(() => {
              console.log('[CAMERA] Video play started');
              startProcessing();
            }).catch(err => {
              console.error('[CAMERA] Video play failed:', err);
              startProcessing();
            });
          }, 100);
        };
        
      } catch (error) {
        updateStatus('Camera access denied or not available: ' + error.message, 'error');
      }
    }

    function stopCamera() {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
        video.srcObject = null;
        isProcessing = false;
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
    let PROCESS_INTERVAL = 100; // Process every 100ms

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

      // Downscale for recognition
      const targetW = 320;
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
        
        const deviceId = getDeviceId();
        
        fetch('/recognize', {
          method: 'POST',
          headers: {
            'X-Device-ID': deviceId
          },
          body: formData
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            updateFaces(data.faces, scale);
            updateCooldownDisplay(data.cooldown);
            showPopupNotification(data.popup);
          } else {
            console.error('Recognition failed:', data.error);
          }
        })
        .catch(error => {
          console.error('Recognition error:', error);
        })
        .finally(() => { inFlight = false; });
      }, 'image/jpeg', 0.4);

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
    
    function updateCooldownDisplay(cooldownInfo) {
      const cooldownDisplay = document.getElementById('cooldown-display');
      const cooldownTime = document.getElementById('cooldown-time');
      
      if (cooldownInfo && cooldownInfo.show) {
        cooldownTime.textContent = cooldownInfo.remaining.toFixed(1);
        cooldownDisplay.classList.remove('hidden');
      } else {
        if (cooldownInfo === false || cooldownInfo === null) {
          cooldownDisplay.classList.add('hidden');
        }
      }
    }
    
    function showPopupNotification(popupInfo) {
      if (!popupInfo || !popupInfo.show) {
        return;
      }
      
      const popup = document.getElementById('popup-notification');
      const popupIcon = document.getElementById('popup-icon');
      const popupTitle = document.getElementById('popup-title');
      const popupMemberName = document.getElementById('popup-member-name');
      const popupMemberId = document.getElementById('popup-member-id');
      const popupMessage = document.getElementById('popup-message');
      
      // Clear any existing timeout
      if (currentPopupTimeout) {
        clearTimeout(currentPopupTimeout);
        currentPopupTimeout = null;
      }
      
      // Set popup style
      popup.className = 'popup-notification';
      if (popupInfo.style === 'GRANTED') {
        popup.classList.add('granted');
        popupIcon.textContent = '✅';
        popupTitle.textContent = 'ACCESS GRANTED';
      } else if (popupInfo.style === 'DENIED') {
        popup.classList.add('denied');
        popupIcon.textContent = '❌';
        popupTitle.textContent = 'ACCESS DENIED';
      }
      
      // Set member information
      popupMemberName.textContent = popupInfo.member_name || 'Unknown Member';
      popupMemberId.textContent = 'Member #' + (popupInfo.member_id || 'N/A');
      popupMessage.textContent = popupInfo.message || 'Welcome to FTL Gym!';
      
      // Show popup
      popup.classList.remove('hidden');
      
      // Hide after 5 seconds
      currentPopupTimeout = setTimeout(() => {
        popup.classList.add('hidden');
        currentPopupTimeout = null;
      }, 5000);
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

    function drawDisplay() {
      if (!isProcessing) return;
      
      if (!video || !video.videoWidth || !video.videoHeight || video.readyState < 2) {
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#fff';
        ctx.font = '20px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('Loading camera...', canvas.width / 2, canvas.height / 2);
        requestAnimationFrame(drawDisplay);
        return;
      }
      
      // Clear canvas
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      
      // Draw video frame
      try {
        if (video.videoWidth > 0 && video.videoHeight > 0) {
          ctx.save();
          ctx.scale(-1, 1);
          ctx.translate(-canvas.width, 0);
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          ctx.restore();
        }
      } catch (e) {
        console.error('[DRAW] Error drawing video:', e);
      }
      
      const now = Date.now();
      const showFaces = (now - lastFacesTime) < FACES_TTL_MS ? lastFaces : [];
      
      // Calculate scaling factors
      const sx = video.videoWidth ? canvas.width / video.videoWidth : 1;
      const sy = video.videoHeight ? canvas.height / video.videoHeight : 1;
      
      for (const face of showFaces) {
        const { x, y, width, height, name, confidence } = face;
        // Adjust coordinates for horizontal flip
        const dx = Math.round((video.videoWidth - x - width) * sx);
        const dy = Math.round(y * sy);
        const dw = Math.round(width * sx);
        const dh = Math.round(height * sy);
        
        // Color based on recognition
        let color = '#ff0000'; // Red for unknown
        if (name !== 'Unknown') {
          color = '#00ff00'; // Green for recognized
        }
        
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(dx, dy, dw, dh);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect(dx, dy + dh - 25, dw, 25);
        ctx.fillStyle = '#ffffff';
        ctx.font = '14px Arial';
        ctx.fillText(name, dx + 5, dy + dh - 8);
      }
      requestAnimationFrame(drawDisplay);
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

    // Cleanup on page unload
    window.addEventListener('beforeunload', stopCamera);
  </script>
</body>
</html>
"""

@main_bp.route("/")
def index():
    """Main page with face recognition interface"""
    return render_template_string(INDEX_HTML)

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

@main_bp.route("/recognition")
def recognition_page():
    """Face recognition page"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import prepare_encodings
    
    try:
        print("[RECOG] Preparing encodings on-demand...")
        prepare_encodings()
    except Exception as e:
        print(f"[RECOG] Prepare error: {e}")
    
    return render_template("recognition.html")
