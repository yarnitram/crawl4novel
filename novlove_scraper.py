import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import argparse # Import argparse for command-line arguments
from bs4 import BeautifulSoup # Import BeautifulSoup for HTML parsing
from database_sqlite import SessionLocal, Genre, create_db_and_tables, Website, Novel, Chapter, NovelInstance, NovelGenre
from sqlalchemy import func # Import func for database functions like now()

def get_genres_from_sitemap(sitemap_url: str):
    """
    Fetches the sitemap, parses it, and extracts genre names.
    """
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
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
                    if len(path_parts) > 2 and path_parts[-1]: # Ensure there's a part after /nov-love-genres/
                        genre_name = path_parts[-1]
                        genres.add(genre_name)
        return list(genres)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching sitemap: {e}")
        return []
    except ET.ParseError as e:
        print(f"Error parsing XML sitemap: {e}")
        return []

def save_genres_to_db(genres: list):
    """
    Saves a list of genre names to the database.
    """
    db = SessionLocal()
    try:
        for genre_name in genres:
            # Check if genre already exists
            existing_genre = db.query(Genre).filter(Genre.name == genre_name).first()
            if not existing_genre:
                new_genre = Genre(name=genre_name)
                db.add(new_genre)
                print(f"Added genre: {genre_name}")
            else:
                print(f"Genre already exists: {genre_name}")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error saving genres to database: {e}")
    finally:
        db.close()

def get_novel_urls_from_sitemap(sitemap_url: str):
    """
    Fetches the sitemap, parses it, and extracts novel URLs.
    """
    try:
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
        return list(novel_urls)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching sitemap: {e}")
        return []
    except ET.ParseError as e:
        print(f"Error parsing XML sitemap: {e}")
        return []

def save_novel_urls_to_db(novel_urls: list, website_name: str = "NovLove", website_url: str = "https://novlove.com"):
    """
    Saves a list of novel URLs to the database, associating them with a website.
    """
    db = SessionLocal()
    try:
        # Get or create the Website entry
        novlove_website = db.query(Website).filter(Website.name == website_name).first()
        if not novlove_website:
            novlove_website = Website(name=website_name, url=website_url)
            db.add(novlove_website)
            db.commit()
            db.refresh(novlove_website)
            print(f"Added new website: {website_name}")
        else:
            print(f"Website already exists: {website_name}")

        for novel_url in novel_urls:
            # Check if novel URL already exists
            existing_novel = db.query(Novel).filter(Novel.source_url == novel_url).first()
            if not existing_novel:
                # Extract title from URL (simple heuristic, might need refinement)
                parsed_url = urlparse(novel_url)
                path_parts = parsed_url.path.split('/')
                # Get the last non-empty part as title, replace hyphens with spaces and title case
                title = path_parts[-2].replace('-', ' ').title() if len(path_parts) > 1 and path_parts[-2] else "Unknown Title"
                
                new_novel = Novel(
                    title=title,
                    source_url=novel_url,
                    source_website_id=novlove_website.id,
                    language="English" # Assuming English for NovLove
                )
                db.add(new_novel)
                print(f"Added novel URL: {novel_url} with title: {title}")
            else:
                print(f"Novel URL already exists: {novel_url}")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error saving novel URLs to database: {e}")
    finally:
        db.close()

def update_novel_details_in_db(novel_id: int, details: dict):
    """
    Updates a novel's details in the database, including handling genres.
    """
    db = SessionLocal()
    try:
        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel:
            print(f"Novel with ID {novel_id} not found.")
            return

        # Update scalar fields
        novel.title = details["title"] if details["title"] else novel.title
        novel.author = details["author"]
        novel.description = details["description"]
        novel.cover_image_url = details["cover_image_url"]
        novel.is_completed = details["is_completed"]
        novel.avg_rating = details["avg_rating"]
        novel.last_scraped_at = func.now()

        # Handle genres: clear existing associations and add new ones
        # Clear existing associations for this novel using ORM
        novel.genres.clear()
        db.flush()  # Flush to ensure deletions are processed before new insertions
        # Then, add new genre associations
        for genre_name in details["genres"]:
            genre = db.query(Genre).filter(Genre.name == genre_name).first()
            if not genre:
                genre = Genre(name=genre_name)
                db.add(genre)
                db.flush() # Flush to get ID for new genre
                print(f"Created new genre: {genre_name}")
            if genre not in novel.genres:
                novel.genres.append(genre) # This will create entries in novel_genres table

        db.add(novel)
        db.commit()
        print(f"Successfully updated details for novel: {novel.title}")
    except Exception as e:
        db.rollback()
        print(f"Error updating novel details for ID {novel_id}: {e}")
    finally:
        db.close()

def scrape_genres_command(sitemap_url: str):
    """
    Command to scrape and save genres from a sitemap URL.
    """
    print(f"Scraping genres from: {sitemap_url}")
    genres = get_genres_from_sitemap(sitemap_url)
    if genres:
        print(f"Found {len(genres)} unique genres.")
        save_genres_to_db(genres)
    else:
        print("No genres found or an error occurred.")

def scrape_novel_urls_command(sitemap_url: str):
    """
    Command to scrape and save novel URLs from a sitemap.
    """


async def scrape_chapters_with_ajax(url: str):
    """
    Scrape novel chapters loaded via AJAX on the tab with id 'tab-chapters-title'.
    """
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    browser_config = BrowserConfig(headless=True, verbose=True)

    # JavaScript to click the tab if needed (optional)
    js_commands = [
        "document.querySelector('#tab-chapters-title')?.click();"
    ]

    # Wait for a selector that appears after AJAX content loads
    wait_for_selector = "css:#chapters-content-loaded"  # Replace with actual selector indicating content loaded

    crawl_config = CrawlerRunConfig(
        js_code=js_commands,
        wait_for=wait_for_selector,
        page_timeout=10000,  # 10 seconds timeout
        verbose=True
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=crawl_config)
        if result.success:
            print("AJAX-loaded content HTML length:", len(result.cleaned_html))
            print(result.cleaned_html[:500])  # Print snippet of loaded content
        else:
            print("Failed to load AJAX content:", result.error_message)
    print(f"Scraping novel URLs from: {sitemap_url}")
    novel_urls = get_novel_urls_from_sitemap(sitemap_url)
    if novel_urls:
        print(f"Found {len(novel_urls)} unique novel URLs.")
        save_novel_urls_to_db(novel_urls)
    else:
        print("No novel URLs found or an error occurred.")

def scrape_novels_and_chapters_command(start_url: str):
    """
    Placeholder for scraping novels and chapters.
    """


def parse_novel_details(html_content: str, novel_url: str):
    """
    Parses the HTML content of a novel detail page and extracts relevant information.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    details = {
        "title": None,
        "author": None,
        "description": None,
        "cover_image_url": None,
        "language": "English", # Default to English for NovLove
        "is_completed": False,
        "avg_rating": None,
        "genres": []
    }

    # Extract title
    title_meta = soup.find('meta', property='og:novel:novel_name')
    if title_meta:
        details["title"] = title_meta.get('content')
    elif soup.find('h3', class_='title'):
        details["title"] = soup.find('h3', class_='title').text.strip()

    # Extract author
    author_meta = soup.find('meta', property='og:novel:author')
    if author_meta:
        details["author"] = author_meta.get('content')
    else:
        author_li = soup.find('ul', class_='info-meta').find('h3', string='Author:').find_next_sibling('a')
        if author_li:
            details["author"] = author_li.text.strip()

    # Extract description
    description_meta = soup.find('meta', attrs={'name': 'description', 'itemprop': 'description'})
    if description_meta:
        details["description"] = description_meta.get('content')
    else:
        desc_div = soup.find('div', class_='desc-text')
        if desc_div:
            details["description"] = desc_div.get_text(separator='\n').strip()

    # Extract cover image URL
    cover_image_meta = soup.find('meta', property='og:image')
    if cover_image_meta:
        details["cover_image_url"] = cover_image_meta.get('content')
    else:
        cover_img = soup.find('img', class_='lazy')
        if cover_img:
            details["cover_image_url"] = cover_img.get('data-src')

    # Extract status (is_completed)
    status_meta = soup.find('meta', property='og:novel:status')
    if status_meta and status_meta.get('content') == "Completed":
        details["is_completed"] = True
    else:
        status_li = soup.find('ul', class_='info-meta').find('h3', string='Status:').find_next_sibling('a')
        if status_li and status_li.text.strip().lower() == "completed":
            details["is_completed"] = True

    # Extract average rating
    rating_span = soup.find('span', itemprop='ratingValue')
    if rating_span:
        try:
            details["avg_rating"] = float(rating_span.text.strip())
        except ValueError:
            details["avg_rating"] = None

    # Extract genres
    genres_meta = soup.find('meta', property='og:novel:genre')
    if genres_meta:
        genres_str = genres_meta.get('content')
        details["genres"] = [g.strip().title() for g in genres_str.split(',')]
    else:
        genre_li = soup.find('ul', class_='info-meta').find('h3', string='Genre:')
        if genre_li:
            genre_links = genre_li.find_next_siblings('a')
            details["genres"] = [link.text.strip() for link in genre_links]

    return details

def scrape_novel_details_command():
    """
    Fetches novel URLs from the database, scrapes their details, and updates the database.
    """


    db = SessionLocal()
    try:
        novels_to_scrape = db.query(Novel).filter(Novel.description == None).all() # Only scrape novels without description
        print(f"Found {len(novels_to_scrape)} novels to scrape details for.")

        for novel in novels_to_scrape:
            print(f"Scraping details for novel: {novel.title} ({novel.source_url})")
            try:
                response = requests.get(novel.source_url)
                response.raise_for_status()
                html_content = response.content
                
                details = parse_novel_details(html_content, novel.source_url)

                # Update novel object
                novel.title = details["title"] if details["title"] else novel.title # Keep existing title if new one is None
                novel.author = details["author"]
                novel.description = details["description"]
                novel.cover_image_url = details["cover_image_url"]
                novel.is_completed = details["is_completed"]
                novel.avg_rating = details["avg_rating"]
                novel.last_scraped_at = func.now() # Update last scraped time

                # Handle genres (many-to-many relationship)
                novel.genres = [] # Clear existing genres
                for genre_name in details["genres"]:
                    genre = db.query(Genre).filter(Genre.name == genre_name).first()
                    if not genre:
                        genre = Genre(name=genre_name)
                        db.add(genre)
                        db.flush() # Flush to get ID for new genre
                        print(f"Created new genre: {genre_name}")
                    novel.genres.append(genre)
                
                db.add(novel)
                db.commit()
                print(f"Successfully updated details for novel: {novel.title}")

            except requests.exceptions.RequestException as e:
                print(f"Error fetching novel URL {novel.source_url}: {e}")
                db.rollback() # Rollback changes for this novel
            except Exception as e:
                print(f"Error parsing/saving details for novel {novel.source_url}: {e}")
                db.rollback() # Rollback changes for this novel
    except Exception as e:
        print(f"Error fetching novels from database: {e}")
    finally:
        db.close()

def scrape_novels_and_chapters_command(start_url: str):
    """
    Placeholder for scraping novels and chapters.
    """


    print(f"Starting novel and chapter scraping from: {start_url}")
    print("This functionality is not yet implemented.")
    # TODO: Implement novel and chapter scraping logic here

def main():
    create_db_and_tables() # Ensure tables are created

    parser = argparse.ArgumentParser(description="NovLove Scraper CLI Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Subparser for 'genres' command
    genres_parser = subparsers.add_parser("genres", help="Scrape genres from the sitemap")
    genres_parser.add_argument("--sitemap-url",
                               default="https://novlove.com/sitemap-0.xml",
                               help="URL of the sitemap to scrape genres from")

    # Subparser for 'novel-urls' command
    novel_urls_parser = subparsers.add_parser("novel-urls", help="Scrape novel URLs from the sitemap")
    novel_urls_parser.add_argument("--sitemap-url",
                                   default="https://novlove.com/sitemap-0.xml", # Corrected sitemap for novels
                                   help="URL of the sitemap to scrape novel URLs from")

    # Subparser for 'scrape-details' command
    scrape_details_parser = subparsers.add_parser("scrape-details", help="Scrape full novel details from stored URLs")

    # Subparser for 'novels' command (for full novel and chapter scraping)
    novels_parser = subparsers.add_parser("novels", help="Scrape full novels and chapters (details)")
    novels_parser.add_argument("--start-url",
                               default="https://novlove.com/", # Default or a specific starting point
                               help="Starting URL for detailed novel and chapter scraping")

    args = parser.parse_args()

    if args.command == "genres":
        scrape_genres_command(args.sitemap_url)
    elif args.command == "novel-urls":
        scrape_novel_urls_command(args.sitemap_url)
    elif args.command == "scrape-details":
        scrape_novel_details_command()
    elif args.command == "novels":
        scrape_novels_and_chapters_command(args.start_url)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()