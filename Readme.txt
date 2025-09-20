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
