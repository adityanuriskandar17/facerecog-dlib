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

// Generate unique device ID
function getDeviceId() {
  let deviceId = localStorage.getItem('deviceId');
  if (!deviceId) {
    deviceId = 'device_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem('deviceId', deviceId);
  }
  return deviceId;
}

// Door ID functionality
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
  setTimeout(() => {
    resizeCanvas();
    console.log('[ORIENTATION] Orientation changed, canvas resized');
  }, 300);
});

// Handle window resize for mobile
window.addEventListener('resize', function() {
  setTimeout(() => {
    resizeCanvas();
    console.log('[RESIZE] Window resized, canvas resized');
  }, 100);
});

// Load saved theme on page load
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
  // Ensure door ID is set for this device via URL param/localStorage
  const savedDoorId = localStorage.getItem('doorId');
  if (!savedDoorId) {
    updateStatus('Door ID belum diset. Tambahkan ?doorid=XXXX pada URL', 'error');
    alert('Door ID belum diset. Tambahkan ?doorid=XXXX pada URL');
    return;
  }
  
  // Proceed to start camera
  const deviceId = getDeviceId();
  console.log(`[CAMERA] Starting camera for device: ${deviceId}`);
  
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
    
    // Force video to load for Brave/Chrome
    video.load();
    
    // Wait for video to be ready before starting processing
    video.onloadedmetadata = function() {
      console.log('[CAMERA] Video metadata loaded');
      console.log('[CAMERA] Video dimensions:', video.videoWidth, 'x', video.videoHeight);
      console.log('[CAMERA] Video ready state:', video.readyState);
      console.log('[CAMERA] Canvas dimensions:', canvas.width, 'x', canvas.height);
      updateStatus(`Camera started successfully! (${video.videoWidth}x${video.videoHeight})`, 'success');
      
      // Force video to play for Brave/Chrome compatibility
      setTimeout(() => {
        video.play().then(() => {
          console.log('[CAMERA] Video play started');
          startProcessing();
        }).catch(err => {
          console.error('[CAMERA] Video play failed:', err);
          // Still start processing even if play fails
          startProcessing();
        });
      }, 100); // Small delay to ensure video is ready
    };
    
    video.onerror = function(e) {
      console.error('[CAMERA] Video error:', e);
      updateStatus('Video error occurred', 'error');
    };
    
    video.oncanplay = function() {
      console.log('[CAMERA] Video can play');
    };
    
    video.onplaying = function() {
      console.log('[CAMERA] Video is playing');
    };
    
    video.onloadeddata = function() {
      console.log('[CAMERA] Video data loaded');
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

function startProcessing() {
  if (isProcessing) return;
  isProcessing = true;
  requestAnimationFrame(drawDisplay);
  processFrame();
}

let lastProcessTime = 0;
let PROCESS_INTERVAL = 60; // recognition cadence - will be adjusted dynamically
let performanceMetrics = {
  avgResponseTime: 0,
  requestCount: 0,
  slowRequests: 0
};

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
  const targetW = 320;  // Reduced from 640 to 320 for faster processing
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
  const requestStartTime = Date.now();
  
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
      const responseTime = Date.now() - requestStartTime;
      updatePerformanceMetrics(responseTime);
      
      if (data.success) {
        updateFaces(data.faces, scale);
        updateCooldownDisplay(data.cooldown);
        console.log('[DEBUG] Received popup data:', data.popup);
        showPopupNotification(data.popup);
      } else {
        console.error('Recognition failed:', data.error);
      }
    })
    .catch(error => {
      console.error('Recognition error:', error);
    })
    .finally(() => { inFlight = false; });
  }, 'image/jpeg', 0.4);  // Reduced quality from 0.6 to 0.4 for faster upload

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
  
  console.log('[COOLDOWN] Received cooldown info:', cooldownInfo);
  
  if (cooldownInfo && cooldownInfo.show) {
    console.log('[COOLDOWN] Showing cooldown for:', cooldownInfo.remaining);
    cooldownTime.textContent = cooldownInfo.remaining.toFixed(1);
    cooldownDisplay.classList.remove('hidden');
  } else {
    // Only hide if cooldown is explicitly false or not provided
    if (cooldownInfo === false || cooldownInfo === null) {
      cooldownDisplay.classList.add('hidden');
    }
    // If cooldownInfo is undefined, don't change display state
  }
}

function showPopupNotification(popupInfo) {
  console.log('[POPUP] Received popup info:', popupInfo);
  
  if (!popupInfo || !popupInfo.show) {
    console.log('[POPUP] No popup to show');
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
  
  console.log('[POPUP] Showing popup:', popupInfo.style, 'for', popupInfo.member_name);
  
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
  } else if (popupInfo.style === 'INFO') {
    popup.classList.add('info');
    popupIcon.textContent = 'ℹ️';
    popupTitle.textContent = 'INFO';
  }
  
  // Set member information
  popupMemberName.textContent = popupInfo.member_name || 'Unknown Member';
  popupMemberId.textContent = `Member #${popupInfo.member_id || 'N/A'}`;
  popupMessage.textContent = popupInfo.message || 'Welcome to FTL Gym!';
  
  // Show popup
  popup.classList.remove('hidden');
  console.log('[POPUP] Popup displayed at:', new Date().toLocaleTimeString());
  
  // Hide after 5 seconds
  currentPopupTimeout = setTimeout(() => {
    console.log('[POPUP] Auto-hiding popup after 5 seconds at:', new Date().toLocaleTimeString());
    popup.classList.add('hidden');
    currentPopupTimeout = null;
  }, 5000);
}

function updatePerformanceMetrics(responseTime) {
  performanceMetrics.requestCount++;
  performanceMetrics.avgResponseTime = (performanceMetrics.avgResponseTime * (performanceMetrics.requestCount - 1) + responseTime) / performanceMetrics.requestCount;
  
  if (responseTime > 1000) {  // Consider > 1 second as slow
    performanceMetrics.slowRequests++;
  }
  
  // Adjust processing interval based on performance
  if (performanceMetrics.requestCount > 10) {  // After 10 requests, start adjusting
    const slowRequestRatio = performanceMetrics.slowRequests / performanceMetrics.requestCount;
    
    if (slowRequestRatio > 0.3) {  // If more than 30% are slow
      PROCESS_INTERVAL = Math.min(PROCESS_INTERVAL + 10, 100);  // Increase interval
      console.log(`[PERF] Performance degraded, increasing interval to ${PROCESS_INTERVAL}ms`);
    } else if (slowRequestRatio < 0.1 && performanceMetrics.avgResponseTime < 500) {  // If less than 10% slow and avg < 500ms
      PROCESS_INTERVAL = Math.max(PROCESS_INTERVAL - 5, 20);  // Decrease interval
      console.log(`[PERF] Performance good, decreasing interval to ${PROCESS_INTERVAL}ms`);
    }
  }
  
  console.log(`[PERF] Response time: ${responseTime}ms, Avg: ${performanceMetrics.avgResponseTime.toFixed(1)}ms, Slow: ${performanceMetrics.slowRequests}/${performanceMetrics.requestCount}`);
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
  if (!video || !canvas || !video.videoWidth || !video.videoHeight) return;
  
  const container = canvas.parentElement;
  const containerWidth = container.clientWidth;
  const containerHeight = container.clientHeight;
  const videoAspectRatio = video.videoWidth / video.videoHeight;
  
  console.log('[RESIZE] Container:', containerWidth, 'x', containerHeight);
  console.log('[RESIZE] Video:', video.videoWidth, 'x', video.videoHeight, 'aspect:', videoAspectRatio);
  
  // For fullscreen mode, use viewport dimensions
  if (container.classList.contains('fullscreen-mode') || document.fullscreenElement) {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    canvas.style.width = '100vw';
    canvas.style.height = '100vh';
    return;
  }
  
  // For mobile devices, use different aspect ratio handling
  const isMobile = window.innerWidth <= 768;
  const isLandscape = window.innerWidth > window.innerHeight;
  
  if (isMobile) {
    // Mobile: use 3:4 aspect ratio for portrait, 4:3 for landscape
    const isPortrait = window.innerHeight > window.innerWidth;
    const targetAspectRatio = isPortrait ? 3/4 : 4/3;
    
    let canvasWidth = containerWidth;
    let canvasHeight = containerWidth / targetAspectRatio;
    
    // If height exceeds container, scale down
    if (canvasHeight > containerHeight) {
      canvasHeight = containerHeight;
      canvasWidth = containerHeight * targetAspectRatio;
    }
    
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
    canvas.style.width = canvasWidth + 'px';
    canvas.style.height = canvasHeight + 'px';
    
    // Center the canvas
    canvas.style.margin = '0 auto';
    canvas.style.display = 'block';
    
    console.log('[RESIZE] Mobile canvas:', canvasWidth, 'x', canvasHeight, 'aspect:', targetAspectRatio, 'portrait:', isPortrait);
  } else {
    // Desktop: fill the entire container
    canvas.width = containerWidth;
    canvas.height = containerHeight;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
  }
  
  console.log('[RESIZE] Canvas set to:', canvas.width, 'x', canvas.height, 'Mobile:', isMobile);
}

function drawDisplay() {
  if (!isProcessing) return;
  
  // Check if video is ready and has dimensions
  if (!video || !video.videoWidth || !video.videoHeight || video.readyState < 2) {
    // Video not ready, show loading message
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#fff';
    ctx.font = '20px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('Loading camera...', canvas.width / 2, canvas.height / 2);
    requestAnimationFrame(drawDisplay);
    return;
  }
  
  // Additional check for Brave/Chrome - ensure video is actually playing
  if (video.paused || video.ended) {
    console.log('[CAMERA] Video is paused or ended, attempting to play');
    video.play().catch(err => console.error('[CAMERA] Play failed:', err));
    requestAnimationFrame(drawDisplay);
    return;
  }
  
  // Resize canvas to match video aspect ratio
  resizeCanvas();
  
  // Clear canvas first
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  
  // Draw video frame
  try {
    // Debug video state
    console.log('[DRAW] Video state:', {
      videoWidth: video.videoWidth,
      videoHeight: video.videoHeight,
      canvasWidth: canvas.width,
      canvasHeight: canvas.height,
      readyState: video.readyState,
      paused: video.paused,
      ended: video.ended
    });
    
    // Ensure video is ready before drawing
    if (video.videoWidth > 0 && video.videoHeight > 0) {
      // Try different drawing methods for better compatibility
      try {
        // For mobile, use cover method to maintain aspect ratio
        const isMobile = window.innerWidth <= 768;
        if (isMobile) {
          // Calculate aspect ratio preserving scaling
          const videoAspect = video.videoWidth / video.videoHeight;
          const canvasAspect = canvas.width / canvas.height;
          
          let sourceX = 0, sourceY = 0, sourceWidth = video.videoWidth, sourceHeight = video.videoHeight;
          let destX = 0, destY = 0, destWidth = canvas.width, destHeight = canvas.height;
          
          if (videoAspect > canvasAspect) {
            // Video is wider, crop sides
            sourceWidth = video.videoHeight * canvasAspect;
            sourceX = (video.videoWidth - sourceWidth) / 2;
          } else {
            // Video is taller, crop top/bottom
            sourceHeight = video.videoWidth / canvasAspect;
            sourceY = (video.videoHeight - sourceHeight) / 2;
          }
          
          // Save context state
          ctx.save();
          // Flip horizontally by scaling and translating
          ctx.scale(-1, 1);
          ctx.translate(-canvas.width, 0);
          // Draw video with horizontal flip
          ctx.drawImage(video, sourceX, sourceY, sourceWidth, sourceHeight, destX, destY, destWidth, destHeight);
          // Restore context state
          ctx.restore();
          console.log('[DRAW] Mobile video frame drawn with aspect ratio preservation and horizontal flip');
        } else {
          // Save context state
          ctx.save();
          // Flip horizontally by scaling and translating
          ctx.scale(-1, 1);
          ctx.translate(-canvas.width, 0);
          // Draw video with horizontal flip
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          // Restore context state
          ctx.restore();
          console.log('[DRAW] Desktop video frame drawn successfully with horizontal flip');
        }
      } catch (drawError) {
        console.error('[DRAW] drawImage failed:', drawError);
        // Fallback: try with source dimensions and horizontal flip
        ctx.save();
        ctx.scale(-1, 1);
        ctx.translate(-canvas.width, 0);
        ctx.drawImage(video, 0, 0, video.videoWidth, video.videoHeight, 0, 0, canvas.width, canvas.height);
        ctx.restore();
        console.log('[DRAW] Video frame drawn with fallback method and horizontal flip');
      }
    } else {
      console.log('[DRAW] Video not ready, skipping draw');
      ctx.fillStyle = '#ff0000';
      ctx.font = '16px Arial';
      ctx.textAlign = 'center';
      ctx.fillText('Video not ready', canvas.width / 2, canvas.height / 2);
    }
  } catch (e) {
    console.error('[DRAW] Error drawing video:', e);
    ctx.fillStyle = '#ff0000';
    ctx.font = '16px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('Video drawing error: ' + e.message, canvas.width / 2, canvas.height / 2);
  }
  
  const now = Date.now();
  const showFaces = (now - lastFacesTime) < FACES_TTL_MS ? lastFaces : [];
  
  // Calculate scaling factors based on actual video dimensions
  const sx = video.videoWidth ? canvas.width / video.videoWidth : 1;
  const sy = video.videoHeight ? canvas.height / video.videoHeight : 1;
  
  for (const face of showFaces) {
    const { x, y, width, height, name, confidence, cooldown, cooldown_remaining } = face;
    // Adjust coordinates for horizontal flip
    const dx = Math.round((video.videoWidth - x - width) * sx);
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
      // Don't show cooldown in bounding box, it will be shown on screen
      ctx.fillText(`${name}`, dx + 5, dy + dh - 8);
    } else {
      ctx.fillText(`${name}`, dx + 5, dy + dh - 8);
    }
  }
  requestAnimationFrame(drawDisplay);
}

// Cleanup on page unload
window.addEventListener('beforeunload', stopCamera);
