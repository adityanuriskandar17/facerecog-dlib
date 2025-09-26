document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('fileInput');
    const captureBtn = document.getElementById('captureBtn');
    const resetBtn = document.getElementById('resetBtn');
    const preview = document.getElementById('newPreview');
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');

    // File input handler
    fileInput.addEventListener('change', () => {
        const file = fileInput.files && fileInput.files[0];
        if (!file) return;
        
        // Validate file size (2MB max)
        if (file.size > 2 * 1024 * 1024) {
            alert('File terlalu besar. Maksimal 2MB.');
            fileInput.value = '';
            return;
        }
        
        // Validate file type
        const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];
        if (!validTypes.includes(file.type)) {
            alert('Format file tidak didukung. Gunakan JPG, PNG, GIF, atau WebP.');
            fileInput.value = '';
            return;
        }
        
        const url = URL.createObjectURL(file);
        preview.src = url;
    });

    // Camera capture handler
    captureBtn.addEventListener('click', async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ 
                video: { 
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                    facingMode: 'user'
                } 
            });
            
            video.srcObject = stream;
            
            await new Promise(r => {
                video.onloadedmetadata = () => {
                    canvas.width = 640;
                    canvas.height = Math.round(640 * (video.videoHeight / video.videoWidth));
                    r();
                };
            });
            
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
            preview.src = dataUrl;
            
            // Stop all video tracks
            stream.getTracks().forEach(track => track.stop());
            
        } catch (error) {
            console.error('Camera access error:', error);
            if (error.name === 'NotAllowedError') {
                alert('Akses kamera ditolak. Mohon izinkan akses kamera untuk mengambil foto.');
            } else if (error.name === 'NotFoundError') {
                alert('Kamera tidak ditemukan. Pastikan kamera terhubung.');
            } else {
                alert('Gagal akses kamera: ' + error.message);
            }
        }
    });

    // Reset handler
    resetBtn.addEventListener('click', () => {
        preview.src = '';
        fileInput.value = '';
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
