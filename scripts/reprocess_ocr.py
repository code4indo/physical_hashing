import asyncio
import logging
import os
import sys
from pathlib import Path

# Add src to path to allow imports
sys.path.append(str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arch_fingerprint.db.session import async_session_factory
from arch_fingerprint.db.models import Document
from arch_fingerprint.ai.ocr import run_ocr_async

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def reprocess_ocr():
    """
    Iterate over documents that have no text content and populate it using OCR.
    """
    logger.info("Starting OCR reprocessing task...")
    
    async with async_session_factory() as session:
        # Query for documents with missing text_content
        # We also check if status is not 'deleted'
        query = select(Document).where(
            (Document.text_content.is_(None) | (Document.text_content == "")) &
            (Document.deleted_at.is_(None))
        ).order_by(Document.id.desc()) # Process newest first? Or oldest? Newest might be more relevant.

        result = await session.execute(query)
        documents = result.scalars().all()
        
        logger.info(f"Found {len(documents)} documents pending OCR processing.")
        
        processed_count = 0
        failed_count = 0
        
        for doc in documents:
            image_path = doc.image_path
            
            # Handle relative paths if necessary (though existing code uses absolute or project-relative)
            if not os.path.exists(image_path):
                # Try relative to project root if absolute fails
                candidate = os.path.abspath(image_path)
                if not os.path.exists(candidate):
                     logger.warning(f"Image not found for Doc ID {doc.id}: {image_path}")
                     failed_count += 1
                     continue
                image_path = candidate
                
            logger.info(f"Processing Doc ID {doc.id}: {image_path}")
            
            try:
                text = await run_ocr_async(image_path)
                
                if text:
                    doc.text_content = text
                    # Could update status if needed, but existing logic might use status for vector indexing.
                    # We'll just update text_content.
                    await session.commit()
                    logger.info(f"Updated Doc ID {doc.id} with {len(text)} chars.")
                    processed_count += 1
                else:
                    logger.warning(f"OCR returned no text for Doc ID {doc.id}")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing Doc ID {doc.id}: {e}")
                failed_count += 1

    logger.info(f"OCR Reprocessing Complete. Processed: {processed_count}, Failed: {failed_count}")

if __name__ == "__main__":
    try:
        asyncio.run(reprocess_ocr())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
