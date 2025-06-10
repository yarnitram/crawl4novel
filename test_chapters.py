import asyncio
from novlove_scraper import test_scrape_chapters_with_crawl4ai

novel_url = "https://novlove.com/novel/the-purgatory-calamity/#tab-chapters-title"  # Replace with the actual novel URL

async def main():
    chapters = await test_scrape_chapters_with_crawl4ai(novel_url)
    print(f"Total chapters scraped: {len(chapters)}")

if __name__ == "__main__":
    asyncio.run(main())