import asyncio
from database_sqlite import SessionLocal, Novel
from novlove_scraper import scrape_chapter_list_and_content

async def update_all_novels():
    db = SessionLocal()
    try:
        novels = db.query(Novel).all()
        if not novels:
            print("No novels found in the database. Please add novels first.")
            return
        for novel in novels:
            print(f"Updating chapters for novel: {novel.title} ({novel.source_url})")
            await scrape_chapter_list_and_content(novel.source_url)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(update_all_novels())