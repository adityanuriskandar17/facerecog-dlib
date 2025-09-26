document.addEventListener('DOMContentLoaded', function() {
    const startCameraBtn = document.getElementById('startCameraBtn');
    const captureBtn = document.getElementById('captureBtn');
    const stopCameraBtn = document.getElementById('stopCameraBtn');
    const resetBtn = document.getElementById('resetBtn');
    const preview = document.getElementById('newPreview');
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    const cameraContainer = document.getElementById('cameraContainer');
    // UI for similarity & loading
    let resultBar = document.getElementById('similarityResult');
    let loader = document.getElementById('processingLoader');
    
    let currentStream = null;

    // Start camera handler
    startCameraBtn.addEventListener('click', async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ 
                video: { 
                    width: { ideal: 640 }, 
                    height: { ideal: 480 },
                    facingMode: 'user'
                } 
            });
            
            currentStream = stream;
            video.srcObject = stream;
            cameraContainer.style.display = 'block';
            preview.style.display = 'none';
            
            // Show/hide buttons
            startCameraBtn.style.display = 'none';
            captureBtn.style.display = 'inline-block';
            stopCameraBtn.style.display = 'inline-block';
            
        } catch (error) {
            if (error.name === 'NotAllowedError') {
                alert('Akses kamera ditolak. Silakan izinkan akses kamera dan coba lagi.');
            } else if (error.name === 'NotFoundError') {
                alert('Kamera tidak ditemukan. Pastikan kamera terhubung.');
            } else {
                alert('Gagal akses kamera: ' + error.message);
            }
        }
    });

    // Capture photo handler
    captureBtn.addEventListener('click', async () => {
        if (video.videoWidth === 0 || video.videoHeight === 0) {
            alert('Kamera belum siap. Tunggu sebentar dan coba lagi.');
            return;
        }
        
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0);
        
        const dataURL = canvas.toDataURL('image/jpeg', 0.8);
        preview.src = dataURL;
        preview.style.display = 'block';
        cameraContainer.style.display = 'none';
        
        // Stop the stream
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
        
        // Show/hide buttons
        startCameraBtn.style.display = 'inline-block';
        captureBtn.style.display = 'none';
        stopCameraBtn.style.display = 'none';

        // Trigger comparison against GymMaster photo
        try {
            if (loader) loader.style.display = 'block';
            if (resultBar) {
                resultBar.textContent = '';
                resultBar.className = 'similarity-result';
            }
            const res = await fetch('/compare-photo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ image: dataURL })
            });
            const contentType = res.headers.get('content-type') || '';
            let json;
            if (contentType.includes('application/json')) {
                json = await res.json();
            } else {
                const text = await res.text();
                throw new Error(text || `HTTP ${res.status}`);
            }
            if (loader) loader.style.display = 'none';
            if (!json.success) {
                alert(json.error || 'Gagal membandingkan foto');
                return;
            }
            const pct = json.similarity ?? 0;
            const dist = json.distance ?? 1.0;
            const match = !!json.match;
            if (resultBar) {
                resultBar.textContent = `Kemiripan: ${pct}% (jarak: ${dist}) ${match ? '✓ Cocok' : '✗ Tidak cocok'}`;
                resultBar.classList.toggle('match', match);
                resultBar.classList.toggle('no-match', !match);
            }
        } catch (e) {
            if (loader) loader.style.display = 'none';
            alert('Terjadi kesalahan saat memproses: ' + (e?.message || e));
        }
    });

    // Stop camera handler
    stopCameraBtn.addEventListener('click', () => {
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
        
        cameraContainer.style.display = 'none';
        preview.style.display = 'none';
        
        // Show/hide buttons
        startCameraBtn.style.display = 'inline-block';
        captureBtn.style.display = 'none';
        stopCameraBtn.style.display = 'none';
    });

    // Reset handler
    resetBtn.addEventListener('click', () => {
        // Stop camera if running
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
        
        preview.src = '';
        preview.style.display = 'none';
        cameraContainer.style.display = 'none';
        
        // Show/hide buttons
        startCameraBtn.style.display = 'inline-block';
        captureBtn.style.display = 'none';
        stopCameraBtn.style.display = 'none';
    });

    // Check if current photo exists and show appropriate message
    const currentPhoto = document.getElementById('currentPhoto');
    if (!currentPhoto.src || currentPhoto.src === window.location.href) {
        currentPhoto.alt = 'Tidak ada foto saat ini';
        currentPhoto.style.display = 'none';
        const noPhotoMsg = document.createElement('p');
        noPhotoMsg.textContent = 'Tidak ada foto saat ini';
        noPhotoMsg.style.color = '#666';
        noPhotoMsg.style.fontStyle = 'italic';
        noPhotoMsg.style.textAlign = 'center';
        noPhotoMsg.style.padding = '40px';
        currentPhoto.parentNode.insertBefore(noPhotoMsg, currentPhoto);
    }
});