import asyncio
import sys
from pathlib import Path

# Add backend directory to python path so we can import app modules
sys.path.append(str(Path(__file__).parent))

from sqlmodel import select
from app.database import get_sync_session
from app.models import Paper
from app.services.pdf_renderer import generate_thumbnail

async def backfill_thumbnails():
    print("Starting thumbnail backfill...")
    session = get_sync_session()
    
    try:
        # Find papers without thumbnails
        statement = select(Paper).where(Paper.thumbnail_url == None)
        papers = session.exec(statement).all()
        
        print(f"Found {len(papers)} papers needing thumbnails.")
        
        for i, paper in enumerate(papers):
            print(f"[{i+1}/{len(papers)}] Processing {paper.arxiv_id}...")
            
            if not paper.pdf_url:
                print(f"  Skipping {paper.arxiv_id}: No PDF URL")
                continue
                
            thumbnail_url = await generate_thumbnail(paper.arxiv_id, paper.pdf_url)
            
            if thumbnail_url:
                paper.thumbnail_url = thumbnail_url
                session.add(paper)
                session.commit()
                print(f"  Generated: {thumbnail_url}")
            else:
                print(f"  Failed to generate thumbnail for {paper.arxiv_id}")
                
    except Exception as e:
        print(f"Error during backfill: {e}")
    finally:
        session.close()
        print("Backfill completed.")

if __name__ == "__main__":
    asyncio.run(backfill_thumbnails())
