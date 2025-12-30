import os
import fitz  # pymupdf
import httpx
from pathlib import Path
from typing import Optional

# Constants
STATIC_DIR = Path(__file__).parent.parent / "static"
THUMBNAILS_DIR = STATIC_DIR / "thumbnails"

# Ensure directories exist
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)


async def generate_thumbnail(arxiv_id: str, pdf_url: str) -> Optional[str]:
    """
    Generates a JPG thumbnail from the first page of an arXiv PDF.
    
    Args:
        arxiv_id: The arXiv ID of the paper (used for filename).
        pdf_url: The URL to download the PDF from.
        
    Returns:
        str: Relative URL path to the thumbnail (e.g., "/static/thumbnails/1234.5678.jpg")
        None: If generation fails.
    """
    filename = f"{arxiv_id}.jpg"
    file_path = THUMBNAILS_DIR / filename
    relative_url = f"/static/thumbnails/{filename}"

    # 1. Check cache
    if file_path.exists():
        return relative_url

    try:
        # 2. Download PDF
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            # Arxiv often requires a user agent
            headers = {
                "User-Agent": "PaperInsight/1.0 (mailto:your-email@example.com)"
            }
            # Modify URL to ensure direct PDF link if needed (arxiv often redirects /abs/ to /pdf/)
            # Usually input pdf_url is already correct (e.g. http://arxiv.org/pdf/2312.00001v1)
            
            response = await client.get(pdf_url, headers=headers)
            response.raise_for_status()
            pdf_data = response.content

        # 3. Render Thumbnail
        # Open PDF from memory
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        
        if len(doc) < 1:
            return None
            
        page = doc[0]
        # Matrix(1.5, 1.5) increases resolution for better quality
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        
        # 4. Save to disk
        pix.save(str(file_path))
        
        return relative_url

    except httpx.HTTPStatusError as e:
        print(f"Failed to download PDF for {arxiv_id}: {e}")
        return None
    except Exception as e:
        print(f"Error generating thumbnail for {arxiv_id}: {e}")
        return None
    finally:
        if 'doc' in locals():
            doc.close()
