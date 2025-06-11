import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import argparse
from database_sqlite import SessionLocal, Genre, create_db_and_tables, Website, Novel, Chapter, NovelInstance, NovelGenre
from sqlalchemy import func
import asyncio
import json
from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

def get_genres_from_sitemap(sitemap_url: str):
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()
        sitemap_content = response.content
        root = ET.fromstring(sitemap_content)
        genres = set()
        for url_element in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
            loc_element = url_element.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
            if loc_element is not None:
                url = loc_element.text
                if url and "https://novlove.com/nov-love-genres/" in url:
                    parsed_url = urlparse(url)
                    path_parts = parsed_url.path.split('/')
                    # Filter out empty strings and get the last non-empty part
                    non_empty_parts = [part for part in path_parts if part]
                    if len(non_empty_parts) > 1: # Ensure there's at least the "nov-love-genres" part and the genre itself
                        genre_name = non_empty_parts[-1]
                        genres.add(genre_name)
        return list(genres)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching sitemap: {e}")
        return []
    except ET.ParseError as e:
        print(f"Error parsing XML sitemap: {e}")
        return []

def save_genres_to_db(genres: list):
    db = SessionLocal()
    for genre_name in genres:
        genre = db.query(Genre).filter(func.lower(Genre.name) == genre_name.lower()).first()
        if not genre:
            genre = Genre(name=genre_name)
            db.add(genre)
            db.commit()
        else:
            db.commit()
    db.close()

async def scrape_novel_details_and_chapters(novel_url: str):
    """
    Scrape novel details and chapters from the given novel URL using crawl4ai.
    """
    # Define extraction schema for novel details
    novel_schema = {
        "name": "NovelDetails",
        "baseSelector": "div.col-novel-main",
        "fields": [
            {"name": "title", "selector": "h3.title", "type": "text"},
            {"name": "author", "selector": "span[itemprop='author'] meta[itemprop='name']", "type": "attribute", "attribute": "content"},
            {"name": "description", "selector": "div.desc-text", "type": "text"},
            {"name": "cover_image_url", "selector": "meta[itemprop='image']", "type": "attribute", "attribute": "content"},
            {"name": "is_completed", "selector": "meta[property='og:novel:status']", "type": "attribute", "attribute": "content"},
            {"name": "avg_rating", "selector": "input#rateVal", "type": "attribute", "attribute": "value"},
            {"name": "genres", "selector": "ul.info.info-meta li", "type": "text"}
        ]
    }

    # Chapter schema moved to scrape_chapter_list_and_content

    browser_cfg = BrowserConfig(
        headless=True,
        verbose=True,
        viewport_width=1280,
        viewport_height=800
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        # Scrape novel details
        novel_config = CrawlerRunConfig(
            wait_for="css:div.col-novel-main",
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=JsonCssExtractionStrategy(novel_schema),
            verbose=True
        )
        novel_result = await crawler.arun(
            url=novel_url,
            config=novel_config
        )

        # Chapter scraping moved to scrape_chapter_list_and_content

        # Parse extracted content
        extracted_novel_details = {} # Use a new variable for the parsed details
        genres_from_html = []
        if novel_result.extracted_content:
            print("Raw novel details extracted content:", novel_result.extracted_content[:500])  # Debug print first 500 chars
            try:
                parsed_content = json.loads(novel_result.extracted_content)
                if isinstance(parsed_content, list) and parsed_content:
                    extracted_novel_details = parsed_content[0]
                elif isinstance(parsed_content, dict):
                    extracted_novel_details = parsed_content
            except Exception as e:
                print(f"Error parsing novel details JSON: {e}")

            # Additional genre extraction from raw HTML using BeautifulSoup
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(novel_result.html, "html.parser")
                genre_li = None
                for li in soup.select("ul.info.info-meta li"):
                    h3 = li.find("h3")
                    if h3 and h3.get_text(strip=True).lower() == "genre:":
                        genre_li = li
                        break
                if genre_li:
                    genre_links = genre_li.find_all("a")
                    genres_from_html = [a.get_text(strip=True) for a in genre_links if a.get_text(strip=True)]
                    print(f"Extracted genres from HTML: {genres_from_html}")
            except Exception as e:
                print(f"Error extracting genres from HTML: {e}")

        chapters = []  # Chapters are scraped in scrape_chapter_list_and_content

        # Save to database
        db = SessionLocal()
        # Find or create novel record
        novel = db.query(Novel).filter(Novel.source_url == novel_url).first()
        if not novel:
            # Get or create the Website record for NovLove
            website = db.query(Website).filter(Website.name == "NovLove").first()
            if not website:
                website = Website(name="NovLove", url="https://novlove.com")
                db.add(website)
                db.commit()
                db.refresh(website)
                print(f"Added new website: {website.name}")

            novel = Novel(
                title=extracted_novel_details.get("title", "Unknown"), # Use extracted_novel_details
                author=extracted_novel_details.get("author"),
                description=extracted_novel_details.get("description"),
                cover_image_url=extracted_novel_details.get("cover_image_url"),
                is_completed=extracted_novel_details.get("is_completed") == "Completed",
                avg_rating=float(extracted_novel_details.get("avg_rating") or 0),
                source_url=novel_url,
                source_website_id=website.id # Assign the website ID
            )
            db.add(novel)
            db.flush()
        else:
            # Update existing novel details
            novel.title = extracted_novel_details.get("title", novel.title) # Use extracted_novel_details
            novel.author = extracted_novel_details.get("author", novel.author)
            novel.description = extracted_novel_details.get("description", novel.description)
            novel.cover_image_url = extracted_novel_details.get("cover_image_url", novel.cover_image_url)
            novel.is_completed = extracted_novel_details.get("is_completed") == "Completed"
            novel.avg_rating = float(extracted_novel_details.get("avg_rating") or novel.avg_rating)

        # Handle genres
        # Prefer genres extracted from HTML if available, else fallback to extracted_novel_details
        genre_names = genres_from_html
        if not genre_names:
            genres_str = extracted_novel_details.get("genres", "")
            if genres_str:
                genre_names = [g.strip() for g in genres_str.split(",") if g.strip()]
        if genre_names:
            print(f"Scraped genres: {', '.join(genre_names)}")  # Log the scraped genres
            for genre_name in genre_names:
                genre = db.query(Genre).filter(func.lower(Genre.name) == genre_name.lower()).first()
                if not genre:
                    genre = Genre(name=genre_name)
                    db.add(genre)
                    db.flush()
                if genre not in novel.genres:
                    novel.genres.append(genre)

        # Chapters are scraped in scrape_chapter_list_and_content
# Assign extracted author from HTML if available
        if extracted_novel_details.get("author"):
            novel.author = extracted_novel_details["author"]
            db.commit()

    # Log results
    print("Novel Details:")
    print(extracted_novel_details)  # Use extracted_novel_details for logging
    # Chapter logging moved to scrape_chapter_list_and_content

    return extracted_novel_details

def scrape_genres_command(sitemap_url: str):
    print("Genre scraping command removed.")
    # Function intentionally left blank as genre scraping is removed.

def scrape_novel_urls_command(sitemap_url: str):
    db = SessionLocal()
    try:
        # Get or create the Website record for NovLove
        website = db.query(Website).filter(Website.name == "NovLove").first()
        if not website:
            website = Website(name="NovLove", url="https://novlove.com")
            db.add(website)
            db.commit()
            db.refresh(website)
            print(f"Added new website: {website.name}")

        response = requests.get(sitemap_url)
        response.raise_for_status()
        sitemap_content = response.content
        root = ET.fromstring(sitemap_content)
        novel_urls = set()
        for url_element in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
            loc_element = url_element.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
            if loc_element is not None:
                url = loc_element.text
                if url and "https://novlove.com/novel/" in url:
                    novel_urls.add(url)
        if not novel_urls:
            print("No novel URLs found in sitemap.")
            return
        
        for novel_url in novel_urls:
            existing_novel = db.query(Novel).filter(Novel.source_url == novel_url).first()
            if not existing_novel:
                new_novel = Novel(title="Unknown", source_url=novel_url, source_website_id=website.id)
                db.add(new_novel)
                print(f"Added novel URL: {novel_url}")
            else:
                print(f"Novel URL already exists: {novel_url}")
        db.commit()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching sitemap: {e}")
        db.rollback()
    except ET.ParseError as e:
        print(f"Error parsing XML sitemap: {e}")

async def scrape_chapter_list_and_content(novel_url: str):
    """
    Scrape chapter list and content from the given novel URL using crawl4ai.
    """
    # Define extraction schema for chapters list
    chapters_schema = {
        "name": "Chapters",
        "baseSelector": "#tab-chapters ul.list-chapter > li",
        "fields": [
            {"name": "chapter_title", "selector": "a", "type": "text"},
            {"name": "chapter_url", "selector": "a", "type": "attribute", "attribute": "href"},
            {"name": "chapter_number", "selector": "a", "type": "text"}
        ]
    }

    # Define extraction schema for chapter content
    chapter_content_schema = {
        "name": "ChapterContent",
        "baseSelector": "div.chapter-content",
        "fields": [
            {"name": "content", "selector": "div.chapter-content", "type": "text"}
        ]
    }

    browser_cfg = BrowserConfig(
        headless=True,
        verbose=True,
        viewport_width=1280,
        viewport_height=800
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        # Scrape chapter list
        chapters_config = CrawlerRunConfig(
            wait_for="css:body",
            delay_before_return_html=10,
            page_timeout=120000,
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=JsonCssExtractionStrategy(chapters_schema),
            verbose=True
        )
        chapters_result = await crawler.arun(
            url=f"{novel_url}#tab-chapters-title",
            config=chapters_config
        )

        chapters = []
        if chapters_result.extracted_content:
            try:
                parsed_chapters = json.loads(chapters_result.extracted_content)
                if isinstance(parsed_chapters, list):
                    chapters = parsed_chapters
            except Exception as e:
                print(f"Error parsing chapters JSON: {e}")

        db = SessionLocal()
        novel = db.query(Novel).filter(Novel.source_url == novel_url).first()
        if not novel:
            print(f"Novel not found in database for URL: {novel_url}")
            db.close()
            return

        latest_chapter_num_on_site = 0
        new_chapters_count = 0

        for chapter_data in chapters:
            chapter_url = chapter_data.get("chapter_url")
            chapter_title = chapter_data.get("chapter_title", "No Title")
            chapter_number_text = chapter_data.get("chapter_number", "")
            try:
                chapter_number = int(''.join(filter(str.isdigit, chapter_number_text)))
            except:
                chapter_number = None

            if chapter_number is None:
                print(f"Skipping chapter with invalid number: {chapter_title}")
                continue

            if chapter_number > latest_chapter_num_on_site:
                latest_chapter_num_on_site = chapter_number

            existing_chapter = db.query(Chapter).filter(Chapter.url == chapter_url).first()
            if existing_chapter:
                # Chapter exists, skip content scraping for now or update if needed
                continue

            # Scrape chapter content
            chapter_content_config = CrawlerRunConfig(
                wait_for="css:div.chapter-content",
                delay_before_return_html=5,
                page_timeout=60000,
                cache_mode=CacheMode.BYPASS,
                extraction_strategy=JsonCssExtractionStrategy(chapter_content_schema),
                verbose=True
            )
            chapter_content_result = await crawler.arun(
                url=chapter_url,
                config=chapter_content_config
            )

            chapter_content = ""
            if chapter_content_result.extracted_content:
                try:
                    parsed_content = json.loads(chapter_content_result.extracted_content)
                    if isinstance(parsed_content, list) and parsed_content:
                        chapter_content = parsed_content[0].get("content", "")
                    elif isinstance(parsed_content, dict):
                        chapter_content = parsed_content.get("content", "")
                except Exception as e:
                    print(f"Error parsing chapter content JSON: {e}")

            new_chapter = Chapter(
                novel_id=novel.id,
                title=chapter_title,
                chapter_number=chapter_number,
                url=chapter_url,
                content=chapter_content
            )
            db.add(new_chapter)
            new_chapters_count += 1
            print(f"Added new chapter: {chapter_title} (Chapter {chapter_number})")
    
            try:
                # Update novel's latest and current chapter numbers
                novel.latest_chapter_number = latest_chapter_num_on_site
                max_chapter_in_db = db.query(func.max(Chapter.chapter_number)).filter(Chapter.novel_id == novel.id).scalar() or 0
                novel.current_last_chapter_number = max_chapter_in_db
    
                db.commit()
                db.close()
    
                print(f"Scraping complete for novel: {novel.title}")
                print(f"New chapters added: {new_chapters_count}")
                print(f"Latest chapter number on site: {latest_chapter_num_on_site}")
                print(f"Current last chapter number in DB: {max_chapter_in_db}")
            except Exception as e:
                db.rollback()
                print(f"Error saving novel URLs to database: {e}")
            finally:
                db.close()

def main():
    create_db_and_tables()

    parser = argparse.ArgumentParser(description="NovLove Scraper CLI Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    genres_parser = subparsers.add_parser("genres", help="Scrape genres from the sitemap")
    genres_parser.add_argument("--sitemap-url",
                               default="https://novlove.com/sitemap-0.xml",
                               help="URL of the sitemap to scrape genres from")

    novel_urls_parser = subparsers.add_parser("novel-urls", help="Scrape novel URLs from the sitemap")
    novel_urls_parser.add_argument("--sitemap-url",
                                   default="https://novlove.com/sitemap-0.xml",
                                   help="URL of the sitemap to scrape novel URLs from")

    scrape_details_parser = subparsers.add_parser("scrape-details", help="Scrape full novel details from stored URLs")
    scrape_details_parser.add_argument("--novel-url", required=False, help="URL of the novel to scrape details and chapters")
    scrape_details_parser.add_argument("--all", action="store_true", help="Scrape details for all novels in the database")
    scrape_details_parser.add_argument("--start-id", type=int, required=False, help="Start novel ID to scrape")
    scrape_details_parser.add_argument("--end-id", type=int, required=False, help="End novel ID to scrape (inclusive)")

    args = parser.parse_args()

    if args.command == "genres":
        scrape_genres_command(args.sitemap_url)
    elif args.command == "novel-urls":
        scrape_novel_urls_command(args.sitemap_url)
    elif args.command == "scrape-details":
        if args.novel_url:
            asyncio.run(scrape_novel_details_and_chapters(args.novel_url))
        elif args.all:
            db = SessionLocal()
            try:
                novels = db.query(Novel).all()
                if not novels:
                    print("No novels found in the database. Please run 'python novlove_scraper.py novel-urls' first.")
                    return
                for novel in novels:
                    print(f"Scraping details for novel: {novel.source_url}")
                    try:
                        asyncio.run(scrape_novel_details_and_chapters(novel.source_url))
                    except Exception as e:
                        print(f"Error scraping novel {novel.source_url}: {e}")
                        print("Skipping to next novel.")
            finally:
                db.close()
        elif args.start_id is not None:
            db = SessionLocal()
            try:
                query = db.query(Novel)
                if args.end_id is not None:
                    query = query.filter(Novel.id >= args.start_id, Novel.id <= args.end_id)
                else:
                    query = query.filter(Novel.id >= args.start_id)
                novels = query.order_by(Novel.id).all()
                if not novels:
                    print(f"No novels found in the database with IDs starting from {args.start_id}.")
                    return
                for novel in novels:
                    print(f"Scraping details for novel ID {novel.id}: {novel.source_url}")
                    try:
                        asyncio.run(scrape_novel_details_and_chapters(novel.source_url))
                    except Exception as e:
                        print(f"Error scraping novel ID {novel.id} ({novel.source_url}): {e}")
                        print("Skipping to next novel.")
            finally:
                db.close()
        else:
            print("Please provide either --novel-url, --all, or --start-id to scrape details and chapters.")

if __name__ == "__main__":
    main()