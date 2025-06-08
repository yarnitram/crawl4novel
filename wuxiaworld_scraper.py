import asyncio
import time
import sqlite3
from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

DB_PATH = "sql_app.db"
BASE_URL_WUXIAWORLD = "https://www.wuxiaworld.com"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS novel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def insert_novel_url(url: str, source: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO novel (url, source) VALUES (?, ?)", (url, source))
        conn.commit()
    finally:
        conn.close()

async def scrape_wuxiaworld_novels():
    print("Scraping wuxiaworld.com...")
    # JavaScript commands to scroll and click "Load More" button on wuxiaworld novel list
    js_commands = [
        "window.scrollTo(0, document.body.scrollHeight);",
        "document.querySelector('button[data-testid=\"load-more-button\"]')?.click();"
    ]

    # Wait condition: wait until novel items count increases beyond a threshold
    wait_for_js = """js:() => {
        const novels = document.querySelectorAll('div.flex.justify-start');
        if (!window.prevCount) {
            window.prevCount = novels.length;
            return false;
        }
        return novels.length > window.prevCount;
    }"""

    # Extraction schema for novel list items
    schema = {
        "name": "Novels",
        "baseSelector": "div.flex.justify-start",
        "fields": [
            {"name": "link", "selector": "a", "type": "attribute", "attribute": "href"}
        ]
    }

    browser_cfg = BrowserConfig(
        headless=True,
        verbose=True,
        viewport_width=1280,
        viewport_height=800
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        # Initial load config
        config_initial = CrawlerRunConfig(
            wait_for="css:div.flex.justify-start",
            session_id="wuxiaworld_scroll_session",
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=JsonCssExtractionStrategy(schema),
            verbose=True
        )

        result = await crawler.arun(
            url=f"{BASE_URL_WUXIAWORLD}/novels",
            config=config_initial
        )

        if not result.success:
            print(f"Initial crawl failed: {result.error_message}")
            return

        import json
        novels_list = json.loads(result.extracted_content) if result.extracted_content else []
        seen_urls = set()
        print(f"Initial novels loaded: {len(novels_list)}")
        for novel in novels_list:
            link = novel.get("link", "")
            if link and link.startswith("/novel/") and link not in seen_urls:
                seen_urls.add(link)
                full_url = BASE_URL_WUXIAWORLD + link
                insert_novel_url(full_url, "wuxiaworld")
                print(f"[{'wuxiaworld'}] {full_url}")

        # Subsequent scrolls/clicks to load more novels
        for i in range(100000):  # Adjust number of scrolls/clicks as needed
            config_scroll = CrawlerRunConfig(
                js_code=js_commands,
                wait_for=wait_for_js,
                js_only=True,
                session_id="wuxiaworld_scroll_session",
                cache_mode=CacheMode.BYPASS,
                extraction_strategy=JsonCssExtractionStrategy(schema),
                verbose=True
            )

            result = await crawler.arun(
                url=f"{BASE_URL_WUXIAWORLD}/novels",
                config=config_scroll
            )

            if not result.success:
                print(f"Scroll {i+1} failed: {result.error_message}")
                break

            # Add delay between scrolls to allow content to load, skip delay before first scroll
            if i > 0:
                time.sleep(3)

            novels_list = json.loads(result.extracted_content) if result.extracted_content else []
            new_novels = 0
            for novel in novels_list:
                link = novel.get("link", "")
                if link and link.startswith("/novel/") and link not in seen_urls:
                    seen_urls.add(link)
                    full_url = BASE_URL_WUXIAWORLD + link
                    insert_novel_url(full_url, "wuxiaworld")
                    print(f"[{'wuxiaworld'}] {full_url}")
                    new_novels += 1
            print(f"Novels loaded after scroll {i+1}: {len(seen_urls)} (new: {new_novels})")

        print("Scraping complete for wuxiaworld.com.")

if __name__ == "__main__":
    init_db()
    asyncio.run(scrape_wuxiaworld_novels())