import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import argparse
from bs4 import BeautifulSoup
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

    # Define extraction schema for chapters
    chapters_schema = {
        "name": "Chapters",
        "baseSelector": "#tab-chapters ul.list-chapter > li",
        "fields": [
            {"name": "chapter_title", "selector": "a", "type": "text"},
            {"name": "chapter_url", "selector": "a", "type": "attribute", "attribute": "href"}
        ]
    }

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

        # Scrape chapters with 5 seconds delay after page load
        chapters_config = CrawlerRunConfig(
            wait_for="css:body", # Waiting for the body to load, relying more on delay
            delay_before_return_html=10, # Changed delay to 10 seconds
            page_timeout=120000, # Keep timeout at 120 seconds
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=JsonCssExtractionStrategy(chapters_schema),
            verbose=True
        )
        chapters_result = await crawler.arun(
            url=f"{novel_url}#tab-chapters-title", # Append the hash to the URL
            config=chapters_config
        )

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

        chapters = []
        if chapters_result.extracted_content:
            try:
                parsed_chapters = json.loads(chapters_result.extracted_content)
                if isinstance(parsed_chapters, list):
                    chapters = parsed_chapters
            except Exception as e:
                print(f"Error parsing chapters JSON: {e}")

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

        # Save chapters
        for chapter_data in chapters:
            chapter_url = chapter_data.get("chapter_url")
            if not chapter_url:
                continue
            existing_chapter = db.query(Chapter).filter(Chapter.url == chapter_url).first()
            if not existing_chapter:
                chapter = Chapter(
                    novel_id=novel.id,
                    title=chapter_data.get("chapter_title", "No Title"),
                    url=chapter_url
                )
                db.add(chapter)
        db.commit()  # Commit all changes (novel, chapters)
# Assign extracted author from HTML if available
        if extracted_novel_details.get("author"):
            novel.author = extracted_novel_details["author"]
            db.commit()

    # Log results
    print("Novel Details:")
    print(extracted_novel_details)  # Use extracted_novel_details for logging
    print("Chapters:")
    for chapter in chapters:
        title = chapter.get("chapter_title", "N/A")
        url = chapter.get("chapter_url", "N/A")
        print(f"{title}: {url}")

    return extracted_novel_details, chapters

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
        db.rollback()
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
                    asyncio.run(scrape_novel_details_and_chapters(novel.source_url))
            finally:
                db.close()
        else:
            print("Please provide either --novel-url or --all to scrape details and chapters.")

if __name__ == "__main__":
    main()