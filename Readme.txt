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