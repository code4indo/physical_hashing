#!/usr/bin/env python3
"""
Script untuk mengecek dokumen di database dan menandai dokumen paleografi.
Dokumen paleografi (tulisan tangan historis) tidak cocok untuk GLM-OCR.
"""

import sqlite3
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = project_root / "data" / "arch_fingerprint.db"

def main():
    print("=" * 80)
    print("PALEOGRAPHY DOCUMENT CHECKER")
    print("=" * 80)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if is_paleography column exists
    cursor.execute("PRAGMA table_info(documents)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'is_paleography' not in columns:
        print("\n📝 Adding 'is_paleography' column to documents table...")
        cursor.execute("""
            ALTER TABLE documents 
            ADD COLUMN is_paleography BOOLEAN DEFAULT 0
        """)
        conn.commit()
        print("✅ Column added successfully!")
    else:
        print("\n✓ 'is_paleography' column already exists")
    
    # List all documents
    print("\n" + "=" * 80)
    print("CURRENT DOCUMENTS")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            id, 
            khazanah, 
            SUBSTR(image_path, 1, 40) as img,
            CASE 
                WHEN text_content IS NOT NULL THEN 'OCR ✓ (' || LENGTH(text_content) || ' chars)'
                ELSE 'No OCR'
            END as ocr_status,
            CASE WHEN is_paleography = 1 THEN 'YES' ELSE 'NO' END as paleography
        FROM documents 
        WHERE status != 'deleted'
        ORDER BY id
    """)
    
    docs = cursor.fetchall()
    
    print(f"\n{'ID':<4} {'Khazanah':<20} {'Image Path':<42} {'OCR Status':<20} {'Paleography'}")
    print("-" * 120)
    
    for doc in docs:
        print(f"{doc[0]:<4} {doc[1]:<20} {doc[2]:<42} {doc[3]:<20} {doc[4]}")
    
    print("\n" + "=" * 80)
    print("PALEOGRAPHY MARKING")
    print("=" * 80)
    print("\nKetik ID dokumen yang merupakan paleografi (pisahkan dengan koma),")
    print("atau tekan Enter untuk skip:")
    
    paleo_input = input("\nDokumen paleografi (contoh: 1,5,7): ").strip()
    
    if paleo_input:
        try:
            paleo_ids = [int(x.strip()) for x in paleo_input.split(',')]
            
            for doc_id in paleo_ids:
                cursor.execute("""
                    UPDATE documents 
                    SET is_paleography = 1 
                    WHERE id = ?
                """, (doc_id,))
                print(f"✓ Dokumen {doc_id} ditandai sebagai paleografi")
            
            conn.commit()
            print(f"\n✅ {len(paleo_ids)} dokumen ditandai sebagai paleografi")
            
        except ValueError as e:
            print(f"❌ Error parsing input: {e}")
            return
    else:
        print("\n⊘ Tidak ada dokumen yang ditandai")
    
    # Show OCR-eligible documents
    print("\n" + "=" * 80)
    print("DOKUMEN YANG ELIGIBLE UNTUK OCR")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            id, 
            khazanah,
            CASE 
                WHEN text_content IS NOT NULL THEN 'Already has OCR'
                ELSE 'Needs OCR'
            END as status
        FROM documents 
        WHERE status != 'deleted' 
          AND (is_paleography IS NULL OR is_paleography = 0)
        ORDER BY id
    """)
    
    eligible_docs = cursor.fetchall()
    
    for doc in eligible_docs:
        status_icon = "✓" if "Already" in doc[2] else "⏳"
        print(f"{status_icon} Doc {doc[0]}: {doc[1]} - {doc[2]}")
    
    print(f"\n📊 Total: {len(eligible_docs)} dokumen eligible untuk OCR")
    
    conn.close()

if __name__ == "__main__":
    main()
