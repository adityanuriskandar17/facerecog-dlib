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
    let meter = document.getElementById('similarityMeter');
    let meterFill = document.getElementById('similarityMeterFill');
    let label = document.getElementById('similarityLabel');
    let burstProgress = document.getElementById('burstProgress');
    const registerActions = document.getElementById('registerActions');
    const burstRegisterBtn = document.getElementById('burstRegisterBtn');
    const uploadGymBtn = document.getElementById('uploadGymBtn');
    const uploadHorizonBtn = document.getElementById('uploadHorizonBtn');
    
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
            // Ensure live preview is not mirrored
            video.style.transform = 'scaleX(-1)';
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

    // Capture photo handler (single compare)
    captureBtn.addEventListener('click', async () => {
        if (video.videoWidth === 0 || video.videoHeight === 0) {
            alert('Kamera belum siap. Tunggu sebentar dan coba lagi.');
            return;
        }
        
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext('2d');
        // Flip horizontally so captured image is not mirrored
        ctx.save();
        ctx.translate(canvas.width, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        ctx.restore();
        
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

            // Category label
            let category = 'Kurang mirip';
            let catClass = 'label-low';
            if (pct >= 75) { category = 'Sangat mirip'; catClass = 'label-high'; }
            else if (pct >= 40) { category = 'Cukup mirip'; catClass = 'label-mid'; }

            if (resultBar) {
                resultBar.textContent = `Kemiripan: ${pct}% (jarak: ${dist})`;
                resultBar.classList.remove('match','no-match');
            }
            if (meter && meterFill) {
                meter.style.display = 'block';
                // animate to percentage
                meterFill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
            }
            if (label) {
                label.style.display = 'block';
                label.className = `similarity-label ${catClass}`;
                label.textContent = category + (match ? ' • Lolos ambang' : ' • Di bawah ambang');
            }
            // Show actions only if not match
            if (registerActions) registerActions.style.display = match ? 'none' : 'flex';
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
        if (registerActions) registerActions.style.display = 'none';
    });

    // Manual burst register handler
    if (burstRegisterBtn) burstRegisterBtn.addEventListener('click', async () => {
        // Prepare UI
        if (loader) loader.style.display = 'block';
        if (burstProgress) burstProgress.textContent = 'Mengambil sampel wajah... 0%';
        if (meter) meter.style.display = 'block';
        if (meterFill) meterFill.style.width = '0%';
        if (label) label.style.display = 'none';

        // Capture burst frames; if stream tidak aktif, buka stream sementara
        const images = [];
        let tempStream = null;
        let srcVideo = video;
        try {
            if (!currentStream || !video.srcObject) {
                tempStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' } });
                const tempVideo = document.createElement('video');
                tempVideo.autoplay = true; tempVideo.muted = true; tempVideo.srcObject = tempStream;
                srcVideo = tempVideo;
                await new Promise(r => setTimeout(r, 120));
            }
            const width = srcVideo.videoWidth || 640;
            const height = srcVideo.videoHeight || 480;
            const bCanvas = document.createElement('canvas');
            bCanvas.width = width; bCanvas.height = height;
            const bCtx = bCanvas.getContext('2d');
            for (let i = 0; i < 20; i++) {
                bCtx.save();
                bCtx.translate(bCanvas.width, 0);
                bCtx.scale(-1, 1);
                bCtx.drawImage(srcVideo, 0, 0, bCanvas.width, bCanvas.height);
                bCtx.restore();
                images.push(bCanvas.toDataURL('image/jpeg', 0.8));
                await new Promise(r => setTimeout(r, 50));
                const pctFrames = Math.round(((i + 1) / 20) * 100);
                if (burstProgress) burstProgress.textContent = `Mengambil sampel wajah... ${pctFrames}%`;
                if (meterFill) meterFill.style.width = `${Math.min(100, Math.round(((i+1)/20)*60))}%`;
            }
        } finally {
            if (tempStream) tempStream.getTracks().forEach(t => t.stop());
        }

        // Send to burst endpoint - email will be auto-detected from session
        const email = (window.CURRENT_EMAIL || '').trim()
        console.log('Sending burst request with email:', email || 'auto-detect from session');
        
        try {
            if (burstProgress) burstProgress.textContent = 'Menghitung encoding...';
            const res = await fetch('/compare-photo-burst', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ images, email: email || null })
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
            const pct = json.similarity ?? 0;
            const dist = json.distance ?? 1.0;
            const match = !!json.match;
            let category = 'Kurang mirip';
            let catClass = 'label-low';
            if (pct >= 75) { category = 'Sangat mirip'; catClass = 'label-high'; }
            else if (pct >= 40) { category = 'Cukup mirip'; catClass = 'label-mid'; }
            if (resultBar) resultBar.textContent = `Kemiripan: ${pct}% (jarak: ${dist})`;
            if (meterFill) meterFill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
            if (label) {
                label.style.display = 'block';
                label.className = `similarity-label ${catClass}`;
                const savedNote = json.saved ? ' • Encoding tersimpan' : '';
                label.textContent = category + (match ? ' • Lolos ambang' : ' • Di bawah ambang') + savedNote;
            }
            if (json.saved) {
                if (burstProgress) burstProgress.textContent = 'Encoding disimpan ke database.';
            } else if (json.save_reason) {
                if (burstProgress) burstProgress.textContent = 'Encoding tidak disimpan: ' + json.save_reason;
            } else {
                if (burstProgress) burstProgress.textContent = '';
            }
            if (registerActions) registerActions.style.display = 'none';
        } catch (e) {
            if (loader) loader.style.display = 'none';
            alert('Terjadi kesalahan saat burst: ' + (e?.message || e));
        }
    });

    // Upload the most recent preview photo to GymMaster
    if (uploadGymBtn) uploadGymBtn.addEventListener('click', async () => {
        try {
            if (!preview.src) {
                alert('Tidak ada foto untuk diupload. Ambil foto terlebih dahulu.');
                return;
            }
            
            // Konfirmasi sebelum upload
            const confirmUpload = confirm('Apakah Anda yakin ingin mengupdate foto ke GymMaster?');
            if (!confirmUpload) {
                return;
            }
            
            if (loader) { loader.style.display = 'block'; if (burstProgress) burstProgress.textContent = 'Mengupload foto ke GymMaster...'; }
            const res = await fetch('/update-member-photo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ image: preview.src })
            });
            const json = await res.json();
            if (loader) loader.style.display = 'none';
            if (!json.success) {
                alert('Gagal update foto: ' + (json?.response?.error || json?.error || 'unknown'));
                return;
            }
            alert('Foto berhasil diupdate ke GymMaster.');
        } catch (e) {
            if (loader) loader.style.display = 'none';
            alert('Gagal upload foto: ' + (e?.message || e));
        }
    });

    // Upload the most recent preview photo to Horizon GCloud
    if (uploadHorizonBtn) uploadHorizonBtn.addEventListener('click', async () => {
        try {
            if (!preview.src) {
                alert('Tidak ada foto untuk diupload. Ambil foto terlebih dahulu.');
                return;
            }
            
            // Konfirmasi sebelum upload
            const confirmUpload = confirm('Apakah Anda yakin ingin mengupdate foto ke Horizon GCloud?');
            if (!confirmUpload) {
                return;
            }
            
            if (loader) { loader.style.display = 'block'; if (burstProgress) burstProgress.textContent = 'Mengupload foto ke Horizon GCloud...'; }
            const res = await fetch('/update-member-photo-horizon', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ image: preview.src })
            });
            const json = await res.json();
            if (loader) loader.style.display = 'none';
            if (!json.success) {
                alert('Gagal update foto ke Horizon: ' + (json?.response?.error || json?.error || 'unknown'));
                return;
            }
            alert('Foto berhasil diupdate ke Horizon GCloud.');
        } catch (e) {
            if (loader) loader.style.display = 'none';
            alert('Gagal upload foto ke Horizon: ' + (e?.message || e));
        }
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