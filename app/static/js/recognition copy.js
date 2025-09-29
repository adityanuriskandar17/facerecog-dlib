// ===================== THEME =====================
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

// ===================== DEVICE ID =====================
function getDeviceId() {
  let deviceId = localStorage.getItem('deviceId');
  if (!deviceId) {
    deviceId = 'device_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem('deviceId', deviceId);
  }
  return deviceId;
}

// ===================== DOOR ID =====================
function setDoorIdParam(doorId) {
  const deviceId = getDeviceId();
  if (!doorId) {
    console.log('[DOOR] No door id provided');
    return;
  }
  console.log(`[DOOR] Setting door ID for device ${deviceId} to: ${doorId}`);
  fetch('/update_door_id', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Device-ID': deviceId
    },
    body: JSON.stringify({ door_id: doorId, device_id: deviceId })
  })
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      updateStatus(`Door set: ${doorId}`, 'success');
    } else {
      updateStatus(`Failed set door: ${data.error}`, 'error');
    }
  })
  .catch(err => updateStatus(`Error set door: ${err}`, 'error'));
}

// ===================== FULLSCREEN =====================
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
      document.querySelector('.container').classList.add('fullscreen-mode');
      fullscreenIcon.textContent = '⛶';
      fullscreenText.textContent = 'Exit';
      resizeCanvas();
    });
  } else {
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
    document.querySelector('.container').classList.remove('fullscreen-mode');
    fullscreenIcon.textContent = '⛶';
    fullscreenText.textContent = 'Fullscreen';
    resizeCanvas();
  }
}

// ESC keluar fullscreen
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && document.fullscreenElement) {
    exitFullscreen();
  }
});

// Pantau perubahan fullscreen
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

// ===================== WINDOW RESIZE =====================
window.addEventListener('resize', function() { resizeCanvas(); });
window.addEventListener('orientationchange', function() {
  setTimeout(resizeCanvas, 300);
});
window.addEventListener('resize', function() {
  setTimeout(resizeCanvas, 100);
});

// ===================== THEME LOAD & DOOR PARAM =====================
document.addEventListener('DOMContentLoaded', function() {
  const savedTheme = localStorage.getItem('theme');
  const themeIcon = document.getElementById('theme-icon');
  if (savedTheme === 'dark') {
    document.body.setAttribute('data-theme', 'dark');
    themeIcon.textContent = '☀️';
  }
  const params = new URLSearchParams(window.location.search);
  const paramDoorId = params.get('doorid') || params.get('door_id') || params.get('door');
  if (paramDoorId) {
    localStorage.setItem('doorId', paramDoorId);
    setDoorIdParam(paramDoorId);
  }
});

// ===================== GLOBAL VAR (VIDEO / CANVAS) =====================
let stream = null;
let video = document.getElementById('video');
let canvas = document.getElementById('canvas');
let ctx = canvas.getContext('2d');
let status = document.getElementById('status');
let isProcessing = false;
let inFlight = false;

// Hasil pengenalan SERVER terakhir (dipakai utk label)
let lastFaces = [];
let lastFacesTime = 0;

// TTL label server (kalau tidak ada deteksi lokal)
const FACES_TTL_MS = 3000;
const SMOOTHING_ALPHA = 0.3;

const workCanvas = document.createElement('canvas');
const workCtx = workCanvas.getContext('2d');

// Popup
let currentPopupTimeout = null;

// ===================== STATUS =====================
function updateStatus(message, type = 'info') {
  status.textContent = message;
  status.className = 'status ' + type;
}

// ===================== CAMERA =====================
async function startCamera() {
  const savedDoorId = localStorage.getItem('doorId');
  if (!savedDoorId) {
    updateStatus('Door ID belum diset. Tambahkan ?doorid=XXXX pada URL', 'error');
    alert('Door ID belum diset. Tambahkan ?doorid=XXXX pada URL');
    return;
  }
  
  const deviceId = getDeviceId();
  console.log(`[CAMERA] Starting camera for device: ${deviceId}`);
  
  try {
    updateStatus('Requesting camera access...', 'info');
    stream = await navigator.mediaDevices.getUserMedia({ 
      video: { width: 960, height: 720, facingMode: 'user' } 
    });
    
    video.srcObject = stream;
    video.load();
    
    video.onloadedmetadata = function() {
      console.log('[CAMERA] Video metadata loaded');
      updateStatus(`Camera started successfully! (${video.videoWidth}x${video.videoHeight})`, 'success');
      setTimeout(() => {
        video.play().then(() => {
          console.log('[CAMERA] Video play started');
          startProcessing();
          initLocalDetector(); // <--- mulai deteksi lokal
        }).catch(err => {
          console.error('[CAMERA] Video play failed:', err);
          startProcessing();
          initLocalDetector(); // <--- tetap inisialisasi
        });
      }, 100);
    };
    
    video.onerror = function(e) {
      console.error('[CAMERA] Video error:', e);
      updateStatus('Video error occurred', 'error');
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
    updateStatus('Camera stopped', 'info');
  }
}

// ===================== SERVER RECOGNITION LOOP =====================
function startProcessing() {
  if (isProcessing) return;
  isProcessing = true;
  requestAnimationFrame(drawDisplay);
  processFrame();
}

let lastProcessTime = 0;
let PROCESS_INTERVAL = 50;
let performanceMetrics = {
  avgResponseTime: 0,
  requestCount: 0,
  slowRequests: 0
};

function processFrame() {
  if (!stream || !video.videoWidth) {
    if (isProcessing) setTimeout(processFrame, 200);
    return;
  }

  const now = Date.now();
  if (now - lastProcessTime < PROCESS_INTERVAL) {
    if (isProcessing) setTimeout(processFrame, 20);
    return;
  }
  lastProcessTime = now;

  const targetW = 320;
  const scale = targetW / video.videoWidth;
  const targetH = Math.round(video.videoHeight * scale);
  workCanvas.width = targetW;
  workCanvas.height = targetH;
  workCtx.drawImage(video, 0, 0, targetW, targetH);

  if (inFlight) {
    if (isProcessing) setTimeout(processFrame, 30);
    return;
  }
  inFlight = true;

  const requestStartTime = Date.now();
  workCanvas.toBlob(function(blob) {
    const formData = new FormData();
    formData.append('frame', blob);
    const deviceId = getDeviceId();
    
    fetch('/recognize', {
      method: 'POST',
      headers: { 'X-Device-ID': deviceId },
      body: formData
    })
    .then(r => r.json())
    .then(data => {
      const rt = Date.now() - requestStartTime;
      updatePerformanceMetrics(rt);
      if (data.success) {
        // Update label/nama dari server (skala balik)
        updateFaces(data.faces, scale);
        // ❌ Jangan override kanvas dengan processed_frame agar bbox tetap kontinu
        // if (data.processed_frame) displayProcessedFrame(data.processed_frame);
        updateCooldownDisplay(data.cooldown);
        showPopupNotification(data.popup);
      } else {
        console.error('Recognition failed:', data.error);
      }
    })
    .catch(err => console.error('Recognition error:', err))
    .finally(() => { inFlight = false; });
  }, 'image/jpeg', 0.4);

  if (isProcessing) setTimeout(processFrame, 100);
}

// (Tetap disimpan kalau nanti ingin dipakai di offscreen)
function displayProcessedFrame(frameBase64) {
  const img = new Image();
  img.onload = function() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const imgAspect = img.width / img.height;
    const canvasAspect = canvas.width / canvas.height;
    let drawWidth, drawHeight, drawX, drawY;
    if (imgAspect > canvasAspect) {
      drawWidth = canvas.width;
      drawHeight = canvas.width / imgAspect;
      drawX = 0; drawY = (canvas.height - drawHeight) / 2;
    } else {
      drawHeight = canvas.height;
      drawWidth = canvas.height * imgAspect;
      drawX = (canvas.width - drawWidth) / 2; drawY = 0;
    }
    ctx.save();
    ctx.scale(-1, 1);
    ctx.translate(-canvas.width, 0);
    ctx.drawImage(img, drawX, drawY, drawWidth, drawHeight);
    ctx.restore();
  };
  img.onerror = function() { console.error('[OPENCV] Failed to load processed frame image'); };
  img.src = 'data:image/jpeg;base64,' + frameBase64;
}

// ===================== UPDATE FACES (HASIL SERVER) =====================
function updateFaces(newFaces, scale) {
  const upscaled = newFaces.map(f => ({
    x: Math.round(f.x / scale),
    y: Math.round(f.y / scale),
    width: Math.round(f.width / scale),
    height: Math.round(f.height / scale),
    name: f.name,
    confidence: f.confidence,
    cooldown: f.cooldown,
    cooldown_remaining: f.cooldown_remaining
  }));
  if (upscaled.length === 0) {
    if (Date.now() - lastFacesTime > 2000) lastFaces = [];
  } else {
    if (lastFaces.length === 0) lastFaces = upscaled;
    else lastFaces = smoothFaces(lastFaces, upscaled);
    lastFacesTime = Date.now();
  }
  console.log(`[FACES] Updated ${upscaled.length} faces, showing ${lastFaces.length} faces`);
}

// ===================== COOLDOWN & POPUP =====================
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
  if (!popupInfo || !popupInfo.show) return;
  const popup = document.getElementById('popup-notification');
  const popupIcon = document.getElementById('popup-icon');
  const popupTitle = document.getElementById('popup-title');
  const popupMemberName = document.getElementById('popup-member-name');
  const popupMemberId = document.getElementById('popup-member-id');
  const popupMessage = document.getElementById('popup-message');

  if (currentPopupTimeout) {
    clearTimeout(currentPopupTimeout);
    currentPopupTimeout = null;
  }

  popup.className = 'popup-notification';
  popup.style.background = '#10b981';
  popup.style.backgroundColor = '#10b981';
  popup.style.opacity = '1';
  popup.style.color = 'white';

  if (popupInfo.style === 'GRANTED') {
    popup.classList.add('granted'); popupIcon.textContent = '✅'; popupTitle.textContent = 'ACCESS GRANTED';
  } else if (popupInfo.style === 'DENIED') {
    popup.classList.add('denied');  popupIcon.textContent = '❌'; popupTitle.textContent = 'ACCESS DENIED';
  } else if (popupInfo.style === 'INFO') {
    popup.classList.add('info');    popupIcon.textContent = 'ℹ️'; popupTitle.textContent = 'INFO';
  }

  popupMemberName.textContent = popupInfo.member_name || 'Unknown Member';
  popupMemberId.textContent = `Member #${popupInfo.member_id || 'N/A'}`;
  popupMessage.textContent = popupInfo.message || 'Welcome to FTL Gym!';
  popup.classList.remove('hidden');

  currentPopupTimeout = setTimeout(() => {
    popup.classList.add('hidden');
    currentPopupTimeout = null;
  }, 5000);
}

// ===================== PERF METRICS =====================
function updatePerformanceMetrics(responseTime) {
  performanceMetrics.requestCount++;
  performanceMetrics.avgResponseTime =
    (performanceMetrics.avgResponseTime * (performanceMetrics.requestCount - 1) + responseTime) /
    performanceMetrics.requestCount;
  if (responseTime > 1000) performanceMetrics.slowRequests++;

  if (performanceMetrics.requestCount > 10) {
    const slowRatio = performanceMetrics.slowRequests / performanceMetrics.requestCount;
    if (slowRatio > 0.3) {
      PROCESS_INTERVAL = Math.min(PROCESS_INTERVAL + 10, 100);
      console.log(`[PERF] Degraded, interval -> ${PROCESS_INTERVAL}ms`);
    } else if (slowRatio < 0.1 && performanceMetrics.avgResponseTime < 500) {
      PROCESS_INTERVAL = Math.max(PROCESS_INTERVAL - 5, 30);
      console.log(`[PERF] Good, interval -> ${PROCESS_INTERVAL}ms`);
    }
  }
  console.log(`[PERF] RT: ${responseTime}ms, Avg: ${performanceMetrics.avgResponseTime.toFixed(1)}ms, Slow: ${performanceMetrics.slowRequests}/${performanceMetrics.requestCount}`);
}

// ===================== SMOOTHING & IoU =====================
function smoothFaces(prev, curr) {
  const result = [];
  const used = new Array(curr.length).fill(false);
  for (let p of prev) {
    let bestIdx = -1, bestIou = 0;
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
        confidence: c.confidence,
        cooldown: c.cooldown ?? p.cooldown,
        cooldown_remaining: c.cooldown_remaining ?? p.cooldown_remaining
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

// ===================== LOCAL DETECTION (BROWSER) =====================
let faceDetector = null;
const LOCAL_DET_INTERVAL = 66; // ~15 FPS
let localBoxes = [];           // bbox lokal terbaru
let renderFaces = [];          // bbox final utk render (gabungan)
const MIN_IOU_ASSOC = 0.2;

function lerp(a, b, t) { return a + (b - a) * t; }

function smoothBox(prev, curr, alpha = SMOOTHING_ALPHA) {
  return {
    x: Math.round(lerp(prev.x, curr.x, alpha)),
    y: Math.round(lerp(prev.y, curr.y, alpha)),
    width: Math.round(lerp(prev.width, curr.width, alpha)),
    height: Math.round(lerp(prev.height, curr.height, alpha)),
    name: curr.name ?? prev.name ?? 'Unknown',
    confidence: curr.confidence ?? prev.confidence,
    cooldown: curr.cooldown ?? prev.cooldown,
    cooldown_remaining: curr.cooldown_remaining ?? prev.cooldown_remaining,
  };
}

function associateLabels(detBoxes, knownFaces) {
  return detBoxes.map(db => {
    let best = null, bestIou = 0;
    for (const k of knownFaces) {
      const iou = boxIoU(db, k);
      if (iou > bestIou) { bestIou = iou; best = k; }
    }
    if (best && bestIou >= MIN_IOU_ASSOC) {
      return { ...db, name: best.name, confidence: best.confidence, cooldown: best.cooldown, cooldown_remaining: best.cooldown_remaining };
    }
    return { ...db, name: 'Unknown' };
  });
}

function initLocalDetector() {
  if ('FaceDetector' in window) {
    try {
      faceDetector = new FaceDetector({ fastMode: true, maxDetectedFaces: 5 });
      console.log('[LOCAL] FaceDetector ready');
      localDetectLoop();
    } catch (e) {
      console.warn('[LOCAL] FaceDetector init failed:', e);
    }
  } else {
    console.warn('[LOCAL] FaceDetector not supported in this browser. Pertimbangkan MediaPipe/WASM.');
  }
}

function localDetectLoop() {
  if (!isProcessing || !faceDetector || !video || video.readyState < 2) {
    setTimeout(localDetectLoop, LOCAL_DET_INTERVAL);
    return;
  }
  faceDetector.detect(video)
    .then(dets => {
      const detBoxes = dets.map(d => ({
        x: Math.round(d.boundingBox.x),
        y: Math.round(d.boundingBox.y),
        width: Math.round(d.boundingBox.width),
        height: Math.round(d.boundingBox.height),
      }));
      const withLabels = associateLabels(detBoxes, lastFaces); // label dari server
      if (localBoxes.length) {
        const used = new Array(withLabels.length).fill(false);
        const smoothed = [];
        for (const pb of localBoxes) {
          let bi = -1, biou = 0;
          for (let i = 0; i < withLabels.length; i++) {
            if (used[i]) continue;
            const iou = boxIoU(pb, withLabels[i]);
            if (iou > biou) { biou = iou; bi = i; }
          }
          if (bi >= 0 && biou >= 0.1) {
            used[bi] = true;
            smoothed.push(smoothBox(pb, withLabels[bi]));
          }
        }
        for (let i = 0; i < withLabels.length; i++) if (!used[i]) smoothed.push(withLabels[i]);
        localBoxes = smoothed;
      } else {
        localBoxes = withLabels;
      }
      lastFacesTime = Date.now(); // agar tidak cepat hilang
    })
    .catch(() => { /* ignore */ })
    .finally(() => setTimeout(localDetectLoop, LOCAL_DET_INTERVAL));
}

// ===================== RESIZE CANVAS =====================
function resizeCanvas() {
  if (!video || !canvas || !video.videoWidth || !video.videoHeight) return;
  const container = canvas.parentElement;
  const containerWidth = container.clientWidth;
  const containerHeight = container.clientHeight;
  const isMobile = window.innerWidth <= 768;

  if (container.classList.contains('fullscreen-mode') || document.fullscreenElement) {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    canvas.style.width = '100vw';
    canvas.style.height = '100vh';
    return;
  }

  if (isMobile) {
    const isPortrait = window.innerHeight > window.innerWidth;
    const targetAspectRatio = isPortrait ? 3/4 : 4/3;
    let canvasWidth = containerWidth;
    let canvasHeight = containerWidth / targetAspectRatio;
    if (canvasHeight > containerHeight) {
      canvasHeight = containerHeight;
      canvasWidth = containerHeight * targetAspectRatio;
    }
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
    canvas.style.width = canvasWidth + 'px';
    canvas.style.height = canvasHeight + 'px';
    canvas.style.margin = '0 auto';
    canvas.style.display = 'block';
  } else {
    canvas.width = containerWidth;
    canvas.height = containerHeight;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
  }
}

// ===================== DRAW LOOP =====================
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

  if (video.paused || video.ended) {
    video.play().catch(err => console.error('[CAMERA] Play failed:', err));
    requestAnimationFrame(drawDisplay);
    return;
  }

  resizeCanvas();

  // Clear bg
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Draw video (mirror)
  try {
    const isMobile = window.innerWidth <= 768;
    if (isMobile) {
      const videoAspect = video.videoWidth / video.videoHeight;
      const canvasAspect = canvas.width / canvas.height;
      let sx = 0, sy = 0, sW = video.videoWidth, sH = video.videoHeight;
      let dx = 0, dy = 0, dW = canvas.width, dH = canvas.height;
      if (videoAspect > canvasAspect) {
        sW = video.videoHeight * canvasAspect;
        sx = (video.videoWidth - sW) / 2;
      } else {
        sH = video.videoWidth / canvasAspect;
        sy = (video.videoHeight - sH) / 2;
      }
      ctx.save();
      ctx.scale(-1, 1);
      ctx.translate(-canvas.width, 0);
      ctx.drawImage(video, sx, sy, sW, sH, dx, dy, dW, dH);
      ctx.restore();
    } else {
      ctx.save();
      ctx.scale(-1, 1);
      ctx.translate(-canvas.width, 0);
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      ctx.restore();
    }
  } catch (e) {
    console.error('[DRAW] Error drawing video:', e);
  }

  // Pilih sumber bbox untuk render
  let facesToRender = [];
  if (localBoxes.length) {
    facesToRender = localBoxes; // tracking kontinu
  } else {
    const now = Date.now();
    facesToRender = (now - lastFacesTime) < FACES_TTL_MS ? lastFaces : [];
  }

  // Skala koordinat (konversi ke canvas space + mirror)
  const sx = video.videoWidth ? canvas.width / video.videoWidth : 1;
  const sy = video.videoHeight ? canvas.height / video.videoHeight : 1;

  for (const face of facesToRender) {
    const { x, y, width, height, name, cooldown } = face;
    const dx = Math.round((video.videoWidth - x - width) * sx);
    const dy = Math.round(y * sy);
    const dw = Math.round(width * sx);
    const dh = Math.round(height * sy);

    let color = '#ff0000';
    if (cooldown) color = '#ffa500';
    else if (name && name !== 'Unknown') color = '#00ff00';

    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.strokeRect(dx, dy, dw, dh);

    ctx.fillStyle = 'rgba(0,0,0,0.8)';
    ctx.fillRect(dx, dy + dh - 25, dw, 25);
    ctx.fillStyle = '#fff';
    ctx.font = '14px Arial';
    ctx.fillText(`${name ?? 'Unknown'}`, dx + 5, dy + dh - 8);
  }

  requestAnimationFrame(drawDisplay);
}

// ===================== CLEANUP =====================
window.addEventListener('beforeunload', stopCamera);
