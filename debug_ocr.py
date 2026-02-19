import asyncio
import logging
from src.arch_fingerprint.ai.ocr import run_ocr_async

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_ocr(image_path):
    print(f"Testing OCR on: {image_path}")
    try:
        result = await run_ocr_async(image_path)
        print("-" * 50)
        print("OCR RESULT:")
        print(result)
        print("-" * 50)
        
        if not result:
            print("WARNING: Result is None or Empty")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Test with the specific image reported by user
    test_image_path = "/data/PROJECT/physical_hashing/data/uploads/13ece276ac044092ae8dfcc8f1978545_raw.png"
    asyncio.run(test_ocr(test_image_path))
