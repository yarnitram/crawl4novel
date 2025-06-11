# Plan for Novel Chapter Scraping and Automation

This plan outlines the steps to enhance the novel scraping application to get the latest chapters, compare them with existing records, and automate the process using cron jobs.

## Overall Flow

```mermaid
graph TD
    A[Start] --> B{User wants to get latest chapters and automate};
    B --> C[Analyze existing scraper (novlove_scraper.py) and DB schema (database_sqlite.py)];
    C --> D[Phase 1: Database Schema Update];
    D --> D0[Add latest_chapter_number and current_last_chapter_number to Novel table];
    D --> D0_1[Add content field to Chapter table];
    D --> E[Phase 2: Refactor Scraping Logic];
    E --> E1[Modify scrape_novel_details_and_chapters to remove chapter scraping];
    E --> E2[Create new async function scrape_chapter_list_and_content(novel_url)];
    E2 --> E2_1[Inside scrape_chapter_list_and_content: Scrape chapter list (title, url, number)];
    E2 --> E2_2[Inside scrape_chapter_list_and_content: Iterate through chapters to scrape content];
    E2 --> E2_3[Inside scrape_chapter_list_and_content: Save/update chapters and content in DB];
    E2 --> E2_4[Inside scrape_chapter_list_and_content: Update latest_chapter_number and current_last_chapter_number in Novel table];
    E2 --> E2_5[Inside scrape_chapter_list_and_content: Implement logging/notification for new chapters/content];
    E --> F[Phase 3: Update CLI Commands];
    F --> F1[Modify existing 'scrape-details' command to only scrape novel details];
    F --> F2[Add new 'scrape-chapters' command to novlove_scraper.py];
    F2 --> F2_1[New 'scrape-chapters' command calls scrape_chapter_list_and_content for single/all novels];
    F --> G[Phase 4: Create Dedicated Script for Daily Updates];
    G --> G1[Create update_novels.py script];
    G1 --> G2[Script connects to DB, retrieves novels to monitor];
    G2 --> G3[Script calls scrape_chapter_list_and_content for each novel];
    G3 --> G4[Script logs update results];
    G --> H[Phase 5: Automate with Cron Jobs];
    H --> H1[Provide Cron Job setup instructions (Linux/macOS)];
    H --> H2[Provide Task Scheduler setup instructions (Windows)];
    H --> I[End];
```

## Detailed Plan Steps

### Phase 1: Database Schema Update

1.  **Add `latest_chapter_number` and `current_last_chapter_number` to `Novel` table:**
    *   Modify the `Novel` model in [`database_sqlite.py`](database_sqlite.py) to include two new integer columns:
        *   `latest_chapter_number`: To store the highest chapter number found on the *website* during the last scrape.
        *   `current_last_chapter_number`: To store the highest chapter number *currently in our database* for that novel.
2.  **Add `content` field to `Chapter` table:**
    *   Modify the `Chapter` model in [`database_sqlite.py`](database_sqlite.py) to include a `content` field (e.g., `Column(Text)`) to store the scraped chapter content.

### Phase 2: Refactor Scraping Logic

1.  **Modify `scrape_novel_details_and_chapters`:**
    *   This function in `novlove_scraper.py` will be updated to *only* scrape novel details (title, author, description, etc.) and save them to the `Novel` table. The chapter scraping logic will be removed from here.
2.  **Create New Asynchronous Function `scrape_chapter_list_and_content(novel_url)`:**
    *   This new function will take a `novel_url` as input.
    *   **Scrape Chapter List:** It will use `crawl4ai` to scrape the list of chapters (title, URL, chapter number) from the novel's page, similar to how it's currently done in `scrape_novel_details_and_chapters`.
    *   **Scrape Chapter Content:** For each chapter URL obtained, it will then make a separate `crawl4ai` call to scrape the actual content of that chapter.
    *   **Save/Update Chapters and Content:** It will check if a chapter already exists in the database by its URL. If it's a new chapter, it will be inserted. If it's an existing chapter, its content will be updated if necessary.
    *   **Update `latest_chapter_number` and `current_last_chapter_number`:** After processing all chapters for a novel, this function will update the `latest_chapter_number` in the `Novel` record with the highest chapter number found on the website during the current scrape. It will also update `current_last_chapter_number` with the highest chapter number now present in our database for that novel.
    *   **Notification/Logging:** Implement logging or print messages when new chapters are identified and their content is scraped and saved.

### Phase 3: Update CLI Commands

1.  **Modify `scrape-details` command:**
    *   The existing `scrape-details` command in `novlove_scraper.py` will be updated to call the modified `scrape_novel_details_and_chapters` function, ensuring it only handles novel details.
2.  **Add New `scrape-chapters` Command:**
    *   A new `argparse` command, `scrape-chapters`, will be added to `novlove_scraper.py`. This command will:
        *   Accept an optional `--novel-url` argument to scrape chapters for a specific novel.
        *   Accept an optional `--all` flag to scrape chapters for all novels currently in the database.
        *   Call the new `scrape_chapter_list_and_content` function accordingly.

### Phase 4: Create a Dedicated Script for Daily Updates

1.  **New Python Script (`update_novels.py`):** I will create a new Python script named `update_novels.py`.
2.  **Database Connection and Novel Retrieval:** This script will establish a database connection and query for all novels (or novel instances) that are marked for monitoring.
3.  **Iterative Scraping:** For each novel retrieved, the script will call the new `scrape_chapter_list_and_content` function to check for and add new chapters and their content.
4.  **Logging Update Results:** The `update_novels.py` script will log the overall results of its run, indicating which novels were checked and how many new chapters were found for each.

### Phase 5: Automate with Cron Jobs

1.  **Cron Job Setup (Linux/macOS):** I will provide clear instructions on how to set up a cron job. This will involve using the `crontab -e` command and adding a line that specifies the schedule (e.g., daily at a certain time) and the command to execute `update_novels.py` using the appropriate Python interpreter.
2.  **Task Scheduler Setup (Windows):** For Windows users, I will provide a brief guide on how to configure a scheduled task using the Task Scheduler utility to run the `update_novels.py` script at desired intervals.