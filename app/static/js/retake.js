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
    const processBtn = document.getElementById('processBtn');
    const burstStartBtn = document.getElementById('burstStartBtn');
    const burstRegisterBtn = document.getElementById('burstRegisterBtn');
    const uploadGymBtn = document.getElementById('uploadGymBtn');
    const uploadHorizonBtn = document.getElementById('uploadHorizonBtn');
    
    // Marker and progress elements
    const markerOverlay = document.getElementById('markerOverlay');
    const burstProgressOverlay = document.getElementById('burstProgressOverlay');
    const burstProgressText = document.getElementById('burstProgressText');
    const burstProgressFill = document.getElementById('burstProgressFill');
    
    // Debug: Check if elements exist
    console.log('Marker overlay element:', markerOverlay);
    console.log('Progress overlay element:', burstProgressOverlay);
    
    let currentStream = null;

    // Helper function to parse response JSON safely
    async function parseResponse(res) {
        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            return await res.json();
        } else {
            const text = await res.text();
            return { success: false, error: text };
        }
    }

    // Start camera handler
    startCameraBtn.addEventListener('click', async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ 
                video: { 
                    width: { ideal: 1280, min: 640 }, 
                    height: { ideal: 720, min: 480 },
                    facingMode: 'user',
                    frameRate: { ideal: 30, min: 15 }
                } 
            });
            
            currentStream = stream;
            video.srcObject = stream;
            // Ensure live preview is not mirrored
            video.style.transform = 'scaleX(-1)';
            cameraContainer.style.display = 'block';
            preview.style.display = 'none';
            
            // Show marker overlay when camera opens
            if (markerOverlay) {
                markerOverlay.style.display = 'block';
                console.log('Marker overlay shown for regular camera');
            }
            
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
        
        // Show process button instead of auto-comparing
        if (processBtn) {
            processBtn.style.display = 'inline-block';
        }

        // Store the captured image data for manual processing
        window.capturedImageData = dataURL;
        
        // Show message that photo is ready for processing
        if (resultBar) {
            resultBar.textContent = 'Foto berhasil diambil. Klik "Proses Foto" untuk membandingkan.';
            resultBar.className = 'similarity-result';
        }
        
        // Don't auto-compare, wait for manual process button click
        return;
    });

    // Process photo handler (manual comparison)
    if (processBtn) {
        processBtn.addEventListener('click', async () => {
            if (!window.capturedImageData) {
                alert('Tidak ada foto untuk diproses. Ambil foto terlebih dahulu.');
                return;
            }
            
            try {
                if (loader) loader.style.display = 'block';
                if (resultBar) {
                    resultBar.textContent = '';
                    resultBar.className = 'similarity-result';
                }
                
                // Retry mechanism for face detection
                let res;
                let json;
                let retryCount = 0;
                const maxRetries = 3;
                
                while (retryCount < maxRetries) {
                    try {
                        res = await fetch('/compare-photo', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            credentials: 'same-origin',
                            body: JSON.stringify({ image: window.capturedImageData })
                        });
                        
                        json = await parseResponse(res);
                        
                        // If face detection failed, try again with different settings
                        if (!json.success && json.error && json.error.includes('No face detected')) {
                            retryCount++;
                            if (retryCount < maxRetries) {
                                console.log(`Face detection failed, retrying... (${retryCount}/${maxRetries})`);
                                await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1 second
                                continue;
                            }
                        }
                        
                        break; // Success or max retries reached
                    } catch (error) {
                        retryCount++;
                        if (retryCount < maxRetries) {
                            console.log(`Request failed, retrying... (${retryCount}/${maxRetries})`);
                            await new Promise(resolve => setTimeout(resolve, 1000));
                            continue;
                        }
                        throw error;
                    }
                }
                
                // Response already parsed in retry loop
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

                // Detect different person (low similarity)
                if (pct < 40) {
                    Swal.fire({
                        title: 'Orang Berbeda',
                        text: 'Kemiripan: ' + pct + '% - Ini adalah orang yang berbeda',
                        icon: 'warning',
                        confirmButtonText: 'OK',
                        confirmButtonColor: '#d33'
                    });
                    
                    // Reset the interface
                    if (resultBar) {
                        resultBar.textContent = 'Orang berbeda terdeteksi! Ambil foto ulang.';
                        resultBar.className = 'similarity-result no-match';
                    }
                    if (meter) meter.style.display = 'none';
                    if (label) label.style.display = 'none';
                    if (processBtn) processBtn.style.display = 'inline-block';
                    
                    // Clear captured image data to force retake
                    window.capturedImageData = null;
                    return;
                }

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
                // Show actions always (regardless of match status)
                if (registerActions) registerActions.style.display = 'flex';
                
                // Hide process button after processing
                if (processBtn) processBtn.style.display = 'none';
                
            } catch (e) {
                if (loader) loader.style.display = 'none';
                alert('Terjadi kesalahan saat memproses: ' + (e?.message || e));
            }
        });
    }

    // Stop camera handler
    stopCameraBtn.addEventListener('click', () => {
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
        
        cameraContainer.style.display = 'none';
        preview.style.display = 'none';
        
        // Hide marker overlay when camera closes
        if (markerOverlay) {
            markerOverlay.style.display = 'none';
            console.log('Marker overlay hidden when camera closes');
        }
        
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
        
        // Show/hide buttons - only reset camera-related buttons
        startCameraBtn.style.display = 'inline-block';
        captureBtn.style.display = 'none';
        stopCameraBtn.style.display = 'none';
        if (processBtn) processBtn.style.display = 'none';
        
        // Keep registerActions visible (don't hide action buttons)
        if (registerActions) registerActions.style.display = 'flex';
        
        // Reset presentation (clear similarity results)
        if (resultBar) {
            resultBar.textContent = '';
            resultBar.className = 'similarity-result';
        }
        if (meter) meter.style.display = 'none';
        if (label) label.style.display = 'none';
        
        // Clear captured image data
        window.capturedImageData = null;
    });

    // Manual burst register handler
    if (burstRegisterBtn) burstRegisterBtn.addEventListener('click', async () => {
        try {
            // Open camera first
            const stream = await navigator.mediaDevices.getUserMedia({ 
                video: { 
                    width: { ideal: 1280, min: 640 }, 
                    height: { ideal: 720, min: 480 }, 
                    frameRate: { ideal: 30, min: 15 } 
                }, 
                audio: false 
            });
            
            currentStream = stream;
            video.srcObject = stream;
            video.play();
            
            // Show camera and hide other elements
            cameraContainer.style.display = 'block';
            preview.style.display = 'none';
            
            // Show marker overlay immediately when camera opens
            if (markerOverlay) {
                markerOverlay.style.display = 'block';
                console.log('Marker overlay shown when camera opens');
            }
            
            // Show/hide buttons
            startCameraBtn.style.display = 'none';
            captureBtn.style.display = 'none';
            stopCameraBtn.style.display = 'inline-block';
            
            // Show burst start button
            if (burstStartBtn) {
                burstStartBtn.style.display = 'inline-block';
            }
            
            // Show message
            if (resultBar) {
                resultBar.textContent = 'Kamera siap untuk burst 20. Klik "Mulai Burst" untuk memulai.';
                resultBar.className = 'similarity-result';
            }
            
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

    // Burst start handler (actual burst capture)
    if (burstStartBtn) {
        burstStartBtn.addEventListener('click', async () => {
            // Show marker overlay and progress
            if (markerOverlay) {
                markerOverlay.style.display = 'block';
                console.log('Marker overlay shown');
            }
            if (burstProgressOverlay) {
                burstProgressOverlay.style.display = 'block';
                console.log('Progress overlay shown');
            }
            
            // Prepare UI
            if (loader) loader.style.display = 'block';
            if (burstProgress) burstProgress.textContent = 'Mengambil sampel wajah... 0%';
            if (meter) meter.style.display = 'block';
            if (meterFill) meterFill.style.width = '0%';
            if (label) label.style.display = 'none';

            // Capture burst frames
            const images = [];
            const width = video.videoWidth || 640;
            const height = video.videoHeight || 480;
            const bCanvas = document.createElement('canvas');
            bCanvas.width = width; bCanvas.height = height;
            const bCtx = bCanvas.getContext('2d');
            for (let i = 0; i < 20; i++) {
                bCtx.save();
                bCtx.translate(bCanvas.width, 0);
                bCtx.scale(-1, 1);
                bCtx.drawImage(video, 0, 0, bCanvas.width, bCanvas.height);
                bCtx.restore();
                
                const dataURL = bCanvas.toDataURL('image/jpeg', 0.8);
                images.push(dataURL);
                
                // Update progress
                const progress = Math.round((i + 1) / 20 * 100);
                if (burstProgress) {
                    burstProgress.textContent = `Mengambil sampel wajah... ${progress}%`;
                }
                if (burstProgressText) {
                    burstProgressText.textContent = `Mengambil sampel wajah... ${i + 1}/20`;
                }
                if (burstProgressFill) {
                    burstProgressFill.style.width = `${progress}%`;
                }
                
                // Wait between captures
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            
            // Hide marker and progress overlay
            if (markerOverlay) markerOverlay.style.display = 'none';
            if (burstProgressOverlay) burstProgressOverlay.style.display = 'none';
            
            // Hide burst start button
            if (burstStartBtn) burstStartBtn.style.display = 'none';
            
            // Process burst images
            try {
                // Get email from login session
                const email = (window.CURRENT_EMAIL || '').trim();
                console.log('Sending burst request with email:', email || 'auto-detect from session');
                
                const res = await fetch('/compare-photo-burst', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ images, email: email || null })
                });
                const json = await parseResponse(res);
                if (loader) loader.style.display = 'none';
                
                // Process results
                const pct = json.similarity ?? 0;
                const dist = json.distance ?? 1.0;
                const match = !!json.match;
                let category = 'Kurang mirip';
                let catClass = 'label-low';
                if (pct >= 75) { category = 'Sangat mirip'; catClass = 'label-high'; }
                else if (pct >= 40) { category = 'Cukup mirip'; catClass = 'label-mid'; }
                
                // Detect different person (low similarity) for burst
                if (pct < 40) {
                    Swal.fire({
                        title: 'Orang Berbeda',
                        text: 'Kemiripan: ' + pct + '% - Ini adalah orang yang berbeda',
                        icon: 'warning',
                        confirmButtonText: 'OK',
                        confirmButtonColor: '#d33'
                    });
                    
                    // Reset the interface
                    if (resultBar) {
                        resultBar.textContent = 'Orang berbeda terdeteksi! Ambil foto ulang.';
                        resultBar.className = 'similarity-result no-match';
                    }
                    if (meter) meter.style.display = 'none';
                    if (label) label.style.display = 'none';
                    if (burstStartBtn) burstStartBtn.style.display = 'inline-block';
                    
                    return;
                }
                
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
                
                // Keep actions visible (don't hide after burst register)
                if (registerActions) registerActions.style.display = 'flex';
                
            } catch (e) {
                if (loader) loader.style.display = 'none';
                alert('Terjadi kesalahan saat burst: ' + (e?.message || e));
            }
        });
    }

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
            const json = await parseResponse(res);
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
            const json = await parseResponse(res);
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