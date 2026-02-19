import sqlite3
import os

DB_PATH = "/data/PROJECT/physical_hashing/data/arch_fingerprint.db"
OUTPUT_FILE = "/data/PROJECT/physical_hashing/ocr_verification_report.txt"

def export_ocr_results():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Select documents with OCR content
        cursor.execute("""
            SELECT id, image_path, text_content 
            FROM documents 
            WHERE text_content IS NOT NULL AND text_content != ''
            ORDER BY id DESC
            LIMIT 10
        """)
        
        rows = cursor.fetchall()
        
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("=== LAPORAN VERIFIKASI HASIL OCR GLM ===\n")
            f.write(f"Database: {DB_PATH}\n")
            f.write(f"Total Dokumen Ditampilkan: {len(rows)}\n\n")
            
            for row in rows:
                doc_id, image_path, text_content = row
                f.write(f"--- DOKUMEN ID: {doc_id} ---\n")
                f.write(f"Image Path: {image_path}\n")
                f.write(f"Panjang Teks: {len(text_content)} karakter\n")
                f.write("-" * 30 + "\n")
                f.write(text_content)
                f.write("\n" + "=" * 50 + "\n\n")
                
        print(f"Laporan berhasil dibuat: {OUTPUT_FILE}")
        print(f"Menampilkan 500 karakter pertama dari laporan:\n")
        
        with open(OUTPUT_FILE, "r") as f:
            print(f.read(500) + "...\n")
            
        conn.close()

    except Exception as e:
        print(f"Error accessing database: {e}")

if __name__ == "__main__":
    export_ocr_results()
