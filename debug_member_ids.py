#!/usr/bin/env python3
"""
Debug script untuk menganalisis masalah member IDs
"""

def debug_member_ids():
    """Debug member ID inconsistencies"""
    try:
        from app.services.database_service import get_conn
        from app.services.redis_service import get_cached_encodings
        from app.services.recognition_service import recognizer
        
        print("=== MEMBER ID DEBUG ANALYSIS ===")
        
        # 1. Check database members with enc data
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT m.id, m.member_id, m.first_name, m.last_name, LENGTH(m.enc) as enc_length
            FROM member m
            WHERE m.enc IS NOT NULL 
            AND LENGTH(m.enc) = 1024
            AND m.status = 1
        """)
        
        db_members = cur.fetchall()
        cur.close()
        conn.close()
        
        print(f"\n=== DATABASE MEMBERS WITH ENC ===")
        print(f"Count: {len(db_members)}")
        for row in db_members:
            print(f"  ID: {row[0]}, Member ID: {row[1]}, Name: {row[2]} {row[3]}, Enc Length: {row[4]}")
        
        # 2. Check Redis cache
        cached_encodings, cached_names, cached_member_ids = get_cached_encodings()
        
        print(f"\n=== REDIS CACHE ===")
        print(f"Encodings: {len(cached_encodings)}")
        print(f"Names: {len(cached_names)}")
        print(f"Member IDs: {cached_member_ids}")
        
        # 3. Check recognizer state
        print(f"\n=== RECOGNIZER STATE ===")
        print(f"Known encodings: {len(recognizer.known_encodings)}")
        print(f"Known names: {len(recognizer.known_names)}")
        print(f"Known IDs: {recognizer.known_ids}")
        print(f"Loaded member IDs: {recognizer.loaded_member_ids}")
        print(f"Gym member mapping: {recognizer.gym_member_id_mapping}")
        
        # 4. Check for inconsistencies
        print(f"\n=== INCONSISTENCY ANALYSIS ===")
        
        db_ids = {row[0] for row in db_members}
        cached_ids = set(cached_member_ids) if cached_member_ids else set()
        loaded_ids = recognizer.loaded_member_ids
        
        print(f"Database IDs: {db_ids}")
        print(f"Cached IDs: {cached_ids}")
        print(f"Loaded IDs: {loaded_ids}")
        
        # Check mismatches
        if db_ids != cached_ids:
            print(f"❌ Database vs Cache mismatch!")
            print(f"   Only in DB: {db_ids - cached_ids}")
            print(f"   Only in Cache: {cached_ids - db_ids}")
        
        if db_ids != loaded_ids:
            print(f"❌ Database vs Loaded mismatch!")
            print(f"   Only in DB: {db_ids - loaded_ids}")
            print(f"   Only in Loaded: {loaded_ids - db_ids}")
        
        if cached_ids != loaded_ids:
            print(f"❌ Cache vs Loaded mismatch!")
            print(f"   Only in Cache: {cached_ids - loaded_ids}")
            print(f"   Only in Loaded: {loaded_ids - cached_ids}")
        
        if db_ids == cached_ids == loaded_ids:
            print("✅ All IDs are consistent!")
        
        # 5. Test auto-check
        print(f"\n=== TESTING AUTO-CHECK ===")
        current_member_ids = recognizer._get_active_members_with_enc()
        print(f"Current DB members: {current_member_ids}")
        print(f"Loaded members: {recognizer.loaded_member_ids}")
        
        new_member_ids = current_member_ids - recognizer.loaded_member_ids
        print(f"New members: {new_member_ids}")
        
        if new_member_ids:
            print("🔄 Would trigger process_new_members_with_enc")
        else:
            print("✅ No new members detected")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_member_ids()
