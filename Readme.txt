-- Migration: Add 'enc' field to member table for storing face encodings
-- Run this SQL to add the encoding field to your member table

-- Check if the field already exists (optional)
SELECT COLUMN_NAME 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_SCHEMA = 'deepface' AND TABLE_NAME = 'member' AND COLUMN_NAME = 'enc';

-- Add the 'enc' field to store face encodings as binary data
ALTER TABLE member ADD COLUMN enc LONGBLOB NULL;

-- Add index for better performance (optional)
CREATE INDEX idx_member_enc ON member(enc(100));

-- Verify the field was added
DESCRIBE member;


Sistem Sekarang:

    ✅ Tidak membaca dari field enc - Bagian loading dari database dikomentar
    ✅ Tidak menyimpan ke field enc - Bagian penyimpanan ke database dikomentar
    ✅ Selalu generate dari gambar - Setiap kali startup, generate encoding baru
    ✅ Tidak ada operasi database - Tidak ada read/write ke field enc
    ✅ Aplikasi berjalan normal - Bisa diakses di http://127.0.0.1:8001
Perilaku Sekarang:

Startup: Generate encoding dari gambar untuk semua member

Tidak ada caching: Encoding tidak disimpan ke database

Fresh generation: Setiap kali restart, generate ulang semua encoding

No DB operations: Tidak ada operasi read/write ke field enc

Untuk Mengembalikan ke Mode Database:
Jika nanti ingin menggunakan field enc lagi, tinggal hapus tanda # dari:
    Baris # stored_encoding = load_encoding_from_db(member_id)
    Baris # save_encoding_to_db(member_id, encoding[0])

Dan semua baris yang terkait di dalam blok if/else
Sekarang sistem akan selalu generate encoding dari gambar setiap kali startup tanpa menyimpan atau membaca dari database!


✅ Code untuk Membuat ENC Otomatis ke Database
Fitur yang Sudah Diimplementasikan:
    Automatic ENC Field Creation (add_enc_field_to_member_table())
        Otomatis menambahkan field enc ke table member jika belum ada
        Field type: LONGBLOB untuk menyimpan binary encoding data

    Smart ENC Loading (load_encoding_from_db())
        Load ENC dari database jika tersedia
        Validasi ukuran ENC (harus 128 float64 values = 1024 bytes)
        Return None jika ENC tidak valid atau tidak ada

    Automatic ENC Generation (build_known_encodings())
        PRIORITAS PERTAMA: Coba load ENC dari database
        FALLBACK: Generate ENC baru dari gambar jika tidak ada di DB
        AUTO SAVE: Simpan ENC yang baru di-generate ke database

    ENC Regeneration Function (regenerate_missing_encodings())
        Regenerate ENC untuk semua member yang tidak punya ENC valid
        Bisa dipanggil manual atau otomatis saat startup

    New API Endpoints:
        GET /enc_status - Cek status ENC semua member
        GET /regenerate_enc - Manual trigger regenerasi ENC
        
    Startup Auto-Processing:
        Otomatis cek dan regenerate ENC yang hilang saat server start
        Log detail proses untuk monitoring