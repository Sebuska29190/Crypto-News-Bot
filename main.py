import os
import asyncio
import logging
import hashlib
import json
import traceback
import aiohttp
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import telegram
from telegram.ext import ApplicationBuilder, CommandHandler
import random

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration (set these as environment variables)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = -1002336450435 #YOUR_CHANNEL_ID
NEWS_CHECK_INTERVAL = 3600  # Check for news every hour (in seconds)

# File to store posted news to avoid duplicates
POSTED_NEWS_FILE = "posted_news.json"

# Common User-Agent strings to rotate for anti-blocking
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0'
]

class CryptoNewsBot:
    def __init__(self):
        self.application = ApplicationBuilder().token(BOT_TOKEN).build()
        self.posted_news = self.load_posted_news()

    def load_posted_news(self):
        """Load previously posted news from file"""
        try:
            with open(POSTED_NEWS_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info(f"No existing posted news file found or file is invalid. Creating new tracking.")
            return {}

    def save_posted_news(self):
        """Save posted news to file"""
        try:
            with open(POSTED_NEWS_FILE, 'w') as f:
                json.dump(self.posted_news, f)
            logger.debug("Successfully saved posted news to file")
        except Exception as e:
            logger.error(f"Error saving posted news: {e}")

    def get_headers(self):
        """Get random browser-like headers to avoid blocking"""
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }

    async def fetch_coindesk_news(self):
        """Fetch news from CoinDesk"""
        news_items = []
        async with aiohttp.ClientSession() as session:
            try:
                logger.info("Fetching news from CoinDesk...")
                # Try the main Bitcoin tag page
                headers = self.get_headers()
                async with session.get("https://www.coindesk.com/tag/bitcoin/", headers=headers, timeout=30) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.debug(f"Received {len(html)} bytes from CoinDesk")

                        soup = BeautifulSoup(html, 'html.parser')

                        # For debugging - save HTML to file to analyze structure
                        if logger.level == logging.DEBUG:
                            with open("coindesk_debug.html", "w", encoding="utf-8") as f:
                                f.write(html)
                            logger.debug("Saved CoinDesk HTML to coindesk_debug.html for analysis")

                        # First try standard article tags
                        articles = soup.select('article')

                        # If no articles found, try other common containers
                        if not articles:
                            articles = soup.select('.article-card, .story-card, .post-card, .featured-post, .story-module, .story, .post, .card')

                        logger.info(f"Found {len(articles)} articles on CoinDesk")

                        if not articles:
                            # Try a different approach - find all links with titles that might be articles
                            potential_articles = soup.select('a[href*="/bitcoin/"], a[href*="/markets/"]')
                            logger.info(f"Trying alternative method, found {len(potential_articles)} potential articles")

                            for link in potential_articles[:15]:  # Process top 15 potential articles
                                try:
                                    href = link.get('href')
                                    # Skip if not a proper article link
                                    if not href or '/tag/' in href or '#' in href:
                                        continue

                                    # Try to find a title within or near the link
                                    title_elem = link.find(text=True, recursive=True)
                                    if not title_elem:
                                        # Try parent or sibling elements
                                        parent = link.parent
                                        title_elem = parent.find(text=True, recursive=True)

                                    title = title_elem.strip() if title_elem else None

                                    # Make sure link is absolute
                                    if href and not href.startswith('http'):
                                        href = f"https://www.coindesk.com{href}"

                                    if title and href and len(title) > 15:  # Filter out too short titles
                                        # Skip navigation links and other non-article content
                                        if any(skip in title.lower() for skip in ['contact', 'about us', 'advertise', 'sign up', 'log in']):
                                            continue

                                        news_items.append({
                                            'title': title,
                                            'link': href,
                                            'source': 'CoinDesk'
                                        })
                                except Exception as e:
                                    logger.debug(f"Error processing potential CoinDesk article: {e}")
                                    continue

                        # Process regular articles if found
                        for article in articles[:10]:
                            try:
                                # Try various title selectors that might match current structure
                                title_elem = None
                                for selector in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', '.headline', '.title', '.card-title', '[data-testid="title"]']:
                                    title_elem = article.select_one(selector)
                                    if title_elem and title_elem.text.strip():
                                        break

                                # Try different link selectors
                                link_elem = None
                                for selector in ['a', 'a.headline-link', '.card a', '[data-testid="title-link"]']:
                                    link_elem = article.select_one(selector)
                                    if link_elem and link_elem.get('href'):
                                        break

                                if not title_elem and not link_elem:
                                    # Last resort: if article has a direct link
                                    if article.name == 'a' and article.get('href'):
                                        link_elem = article
                                        # Try to extract text from the article itself
                                        title_elem = article

                                # Extract title and link safely
                                title = title_elem.text.strip() if title_elem else None
                                link = link_elem.get('href') if link_elem else None

                                # Make sure link is absolute
                                if link and not link.startswith('http'):
                                    link = f"https://www.coindesk.com{link}"

                                if title and link and len(title) > 10:  # Ensure minimum title length
                                    logger.debug(f"Found article: {title[:30]}... - {link}")
                                    news_items.append({
                                        'title': title,
                                        'link': link,
                                        'source': 'CoinDesk'
                                    })
                                else:
                                    logger.debug(f"Skipping article with missing/invalid title or link")
                            except Exception as e:
                                logger.error(f"Error processing CoinDesk article: {e}")
                                continue
                    else:
                        logger.warning(f"Failed to fetch from CoinDesk, status code: {response.status}")

                # If no news found on tag page, try the main markets page
                if not news_items:
                    logger.info("Trying CoinDesk markets page...")
                    headers = self.get_headers()  # Get fresh headers
                    async with session.get("https://www.coindesk.com/markets/", headers=headers, timeout=30) as response:
                        if response.status == 200:
                            html = await response.text()
                            logger.debug(f"Received {len(html)} bytes from CoinDesk markets page")

                            soup = BeautifulSoup(html, 'html.parser')

                            # Try various container selectors
                            articles = soup.select('article, .article-card, .story-card, .post-card, .card')
                            logger.info(f"Found {len(articles)} articles on CoinDesk markets page")

                            for article in articles[:10]:
                                try:
                                    # Extract title and link using same logic as above
                                    title_elem = None
                                    for selector in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', '.headline', '.title', '.card-title']:
                                        title_elem = article.select_one(selector)
                                        if title_elem and title_elem.text.strip():
                                            break

                                    link_elem = article.select_one('a')

                                    title = title_elem.text.strip() if title_elem else None
                                    link = link_elem.get('href') if link_elem else None

                                    # Make sure link is absolute
                                    if link and not link.startswith('http'):
                                        link = f"https://www.coindesk.com{link}"

                                    if title and link and len(title) > 10:
                                        # Only add bitcoin-related news
                                        title_lower = title.lower()
                                        if 'bitcoin' in title_lower or 'btc' in title_lower or 'crypto' in title_lower:
                                            news_items.append({
                                                'title': title,
                                                'link': link,
                                                'source': 'CoinDesk'
                                            })
                                except Exception as e:
                                    logger.error(f"Error processing CoinDesk markets article: {e}")
                                    continue
                        else:
                            logger.warning(f"Failed to fetch from CoinDesk markets page, status code: {response.status}")
            except aiohttp.ClientError as e:
                logger.error(f"Network error fetching CoinDesk news: {e}")
            except Exception as e:
                logger.error(f"Unexpected error fetching CoinDesk news: {e}")
                logger.error(traceback.format_exc())

        logger.info(f"Retrieved {len(news_items)} news items from CoinDesk")
        return news_items

    async def fetch_cointelegraph_news(self):
        """Fetch news from CoinTelegraph"""
        news_items = []
        async with aiohttp.ClientSession() as session:
            try:
                logger.info("Fetching news from CoinTelegraph...")
                # Add user-agent and other headers to mimic browser
                headers = self.get_headers()
                async with session.get("https://cointelegraph.com/tags/bitcoin", headers=headers, timeout=30) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.debug(f"Received {len(html)} bytes from CoinTelegraph")

                        soup = BeautifulSoup(html, 'html.parser')

                        # For debugging - save HTML to file
                        if logger.level == logging.DEBUG:
                            with open("cointelegraph_debug.html", "w", encoding="utf-8") as f:
                                f.write(html)
                            logger.debug("Saved CoinTelegraph HTML to cointelegraph_debug.html for analysis")

                        # Try different article selectors
                        articles = soup.select('.post-card-inline, .post-card, article, .posts-listing__item')

                        # If nothing found, try more generic selectors
                        if not articles:
                            articles = soup.select('.card, .news-item, .article, .post, .story')

                        logger.info(f"Found {len(articles)} articles on CoinTelegraph")

                        if not articles:
                            # Try alternative approach - find main list containers
                            containers = soup.select('.posts-listing, .articles-list, .news-feed, main, .content')

                            if containers:
                                # Extract links from containers that might be articles
                                for container in containers:
                                    links = container.select('a[href*="/news/"], a[href*="/bitcoin/"]')
                                    logger.info(f"Found {len(links)} potential article links in container")

                                    for link in links[:15]:
                                        try:
                                            href = link.get('href')

                                            # Skip navigation links
                                            if not href or '/tags/' in href or '#' in href:
                                                continue

                                            # Try to find title
                                            title = None

                                            # First look for title in link text
                                            if link.text and link.text.strip():
                                                title = link.text.strip()

                                            # If no title in link text, try child elements
                                            if not title:
                                                title_elem = link.select_one('h1, h2, h3, h4, h5, h6, .title, .heading')
                                                if title_elem:
                                                    title = title_elem.text.strip()

                                            # If still no title, look in parent elements
                                            if not title:
                                                parent = link.parent
                                                title_elem = parent.select_one('h1, h2, h3, h4, h5, h6, .title, .heading')
                                                if title_elem:
                                                    title = title_elem.text.strip()

                                            # Make sure link is absolute
                                            if href and not href.startswith('http'):
                                                href = f"https://cointelegraph.com{href}"

                                            if title and href and len(title) > 15:
                                                # Skip navigation and non-article content
                                                if any(skip in title.lower() for skip in ['contact', 'about us', 'advertise', 'sign up', 'log in']):
                                                    continue

                                                news_items.append({
                                                    'title': title,
                                                    'link': href,
                                                    'source': 'CoinTelegraph'
                                                })
                                        except Exception as e:
                                            logger.debug(f"Error processing potential CoinTelegraph article link: {e}")
                                            continue

                        # Process regular articles if found
                        for article in articles[:10]:
                            try:
                                # Try different title selectors
                                title_elem = None
                                for selector in ['.post-card-inline__title', '.post-card__title', 'h1', 'h2', 'h3', 'h4', '.title', '.headline']:
                                    title_elem = article.select_one(selector)
                                    if title_elem and title_elem.text.strip():
                                        break

                                # Try to find link
                                link_elem = article.select_one('a')

                                # Extract title and link safely
                                title = title_elem.text.strip() if title_elem else None
                                link = link_elem.get('href') if link_elem else None

                                # Make sure link is absolute
                                if link and not link.startswith('http'):
                                    link = f"https://cointelegraph.com{link}"

                                if title and link and len(title) > 10:
                                    logger.debug(f"Found article: {title[:30]}... - {link}")
                                    news_items.append({
                                        'title': title,
                                        'link': link,
                                        'source': 'CoinTelegraph'
                                    })
                                else:
                                    logger.debug(f"Skipping article with missing/invalid title or link")
                            except Exception as e:
                                logger.error(f"Error processing CoinTelegraph article: {e}")
                                continue
                    else:
                        logger.warning(f"Failed to fetch from CoinTelegraph, status code: {response.status}")

                # If no articles found or access was denied, try the homepage as fallback
                if not news_items or response.status == 403:
                    logger.info("Trying CoinTelegraph homepage as fallback...")
                    # Get fresh headers and add a delay to avoid detection
                    await asyncio.sleep(2)
                    headers = self.get_headers()
                    async with session.get("https://cointelegraph.com/", headers=headers, timeout=30) as response:
                        if response.status == 200:
                            html = await response.text()
                            logger.debug(f"Received {len(html)} bytes from CoinTelegraph homepage")

                            soup = BeautifulSoup(html, 'html.parser')

                            # Find all news items on homepage
                            articles = soup.select('article, .post-card, .news-card, .article-card')
                            logger.info(f"Found {len(articles)} articles on CoinTelegraph homepage")

                            for article in articles[:10]:
                                try:
                                    title_elem = article.select_one('h1, h2, h3, h4, h5, h6, .title, .headline')
                                    link_elem = article.select_one('a')

                                    title = title_elem.text.strip() if title_elem else None
                                    link = link_elem.get('href') if link_elem else None

                                    # Make sure link is absolute
                                    if link and not link.startswith('http'):
                                        link = f"https://cointelegraph.com{link}"

                                    if title and link and len(title) > 10:
                                        # Only add bitcoin-related news
                                        title_lower = title.lower()
                                        if 'bitcoin' in title_lower or 'btc' in title_lower or 'crypto' in title_lower:
                                            news_items.append({
                                                'title': title,
                                                'link': link,
                                                'source': 'CoinTelegraph'
                                            })
                                except Exception as e:
                                    logger.error(f"Error processing CoinTelegraph homepage article: {e}")
                                    continue
                        else:
                            logger.warning(f"Failed to fetch from CoinTelegraph homepage, status code: {response.status}")
            except aiohttp.ClientError as e:
                logger.error(f"Network error fetching CoinTelegraph news: {e}")
            except Exception as e:
                logger.error(f"Unexpected error fetching CoinTelegraph news: {e}")
                logger.error(traceback.format_exc())

        logger.info(f"Retrieved {len(news_items)} news items from CoinTelegraph")
        return news_items

    # Other methods (is_news_posted, mark_as_posted, clean_old_posts, etc.) remain the same
    def is_news_posted(self, news_item):
        """Check if news has been posted before by creating a unique hash"""
        try:
            if not isinstance(news_item, dict) or 'title' not in news_item or 'link' not in news_item:
                logger.error(f"Invalid news item format: {news_item}")
                return True  # Skip invalid items

            news_hash = hashlib.md5(f"{news_item['title']}:{news_item['link']}".encode()).hexdigest()
            return news_hash in self.posted_news
        except Exception as e:
            logger.error(f"Error checking if news is posted: {e}")
            return True  # Assume it's posted if there's an error

    def mark_as_posted(self, news_item):
        """Mark a news item as posted"""
        try:
            news_hash = hashlib.md5(f"{news_item['title']}:{news_item['link']}".encode()).hexdigest()
            self.posted_news[news_hash] = {
                'title': news_item['title'],
                'timestamp': datetime.now().isoformat()
            }
            self.save_posted_news()
        except Exception as e:
            logger.error(f"Error marking news as posted: {e}")

    def clean_old_posts(self, days=7):
        """Remove posts older than specified days"""
        try:
            now = datetime.now()
            to_remove = []

            for news_hash, data in self.posted_news.items():
                try:
                    if not isinstance(data, dict) or 'timestamp' not in data:
                        # Fix corrupted entries
                        to_remove.append(news_hash)
                        continue

                    post_time = datetime.fromisoformat(data['timestamp'])
                    if now - post_time > timedelta(days=days):
                        to_remove.append(news_hash)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Error processing post {news_hash}: {e}")
                    to_remove.append(news_hash)

            for news_hash in to_remove:
                self.posted_news.pop(news_hash, None)

            if to_remove:
                self.save_posted_news()
                logger.info(f"Cleaned {len(to_remove)} old posts")
        except Exception as e:
            logger.error(f"Error cleaning old posts: {e}")

    async def post_news_to_channel(self, news_item):
        """Post a news item to the Telegram channel"""
        if not isinstance(news_item, dict) or 'title' not in news_item or 'source' not in news_item or 'link' not in news_item:
            logger.error(f"Invalid news item format for posting: {news_item}")
            return False

        message = f"📢 *{news_item['source']}* 📢\n\n" \
                 f"*{news_item['title']}*\n\n" \
                 f"[Read more]({news_item['link']})"

        try:
            await self.application.bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode=telegram.constants.ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            logger.info(f"Posted news: {news_item['title']}")
            self.mark_as_posted(news_item)
            return True
        except Exception as e:
            logger.error(f"Error posting to channel: {e}")
            logger.error(traceback.format_exc())
            return False

    async def check_and_post_news(self):
        """Check for new crypto news and post them"""
        try:
            # Clean old posts periodically
            self.clean_old_posts()

            # Fetch news from different sources
            coindesk_news = await self.fetch_coindesk_news()
            cointelegraph_news = await self.fetch_cointelegraph_news()

            # Validate news items are in correct format
            valid_coindesk_news = []
            valid_cointelegraph_news = []

            for news in coindesk_news:
                if isinstance(news, dict) and all(k in news for k in ['title', 'link', 'source']):
                    valid_coindesk_news.append(news)
                else:
                    logger.warning(f"Invalid news item format from CoinDesk: {news}")

            for news in cointelegraph_news:
                if isinstance(news, dict) and all(k in news for k in ['title', 'link', 'source']):
                    valid_cointelegraph_news.append(news)
                else:
                    logger.warning(f"Invalid news item format from CoinTelegraph: {news}")

            # Combine news from all sources
            all_news = valid_coindesk_news + valid_cointelegraph_news
            logger.info(f"Total valid news items: {len(all_news)}")

            # Post only new news
            posts_count = 0
            for news_item in all_news:
                if not self.is_news_posted(news_item):
                    success = await self.post_news_to_channel(news_item)
                    if success:
                        posts_count += 1
                    # Add a small delay between posts to avoid flooding
                    await asyncio.sleep(2)

                    # Limit to posting maximum 5 news items at once
                    if posts_count >= 5:
                        break

            logger.info(f"Posted {posts_count} new news items")
        except Exception as e:
            logger.error(f"Error in check_and_post_news: {e}")
            logger.error(traceback.format_exc())

    async def cmd_check_news(self, update, context):
        """Handler for /checknews command"""
        try:
            await update.message.reply_text("Checking for new crypto news...")
            await self.check_and_post_news()
            await update.message.reply_text("News check completed!")
        except Exception as e:
            logger.error(f"Error handling checknews command: {e}")
            await update.message.reply_text("An error occurred while checking news. Please check the logs.")

    async def scheduled_news_check(self):
        """Periodically check for news"""
        while True:
            try:
                logger.info("Running scheduled news check...")
                await self.check_and_post_news()
                logger.info(f"Next check in {NEWS_CHECK_INTERVAL} seconds")
            except Exception as e:
                logger.error(f"Error in scheduled news check: {e}")

            await asyncio.sleep(NEWS_CHECK_INTERVAL)

async def main():
    # Check if the token is set
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return

    if not CHANNEL_ID:
        logger.error("CHANNEL_ID environment variable is not set!")
        return

    # Initialize bot
    bot = CryptoNewsBot()

    # Register command handlers
    bot.application.add_handler(CommandHandler("checknews", bot.cmd_check_news))

    # Start the bot
    logger.info("Starting bot...")

    news_check_task = None

    try:
        # Start the application
        await bot.application.initialize()
        await bot.application.start()
        await bot.application.updater.start_polling()

        # Run initial news check
        logger.info("Running initial news check...")
        await bot.check_and_post_news()

        # Start scheduled news checks
        logger.info("Starting scheduled news checks...")
        news_check_task = asyncio.create_task(bot.scheduled_news_check())

        # Keep the program running
        while True:
            await asyncio.sleep(60)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopping...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
    finally:
        # Clean up
        try:
            # Cancel the news check task if it exists
            if news_check_task and not news_check_task.done():
                news_check_task.cancel()
                try:
                    await news_check_task
                except asyncio.CancelledError:
                    pass

            # Shutdown the application
            if hasattr(bot, 'application'):
                if hasattr(bot.application, 'updater'):
                    await bot.application.updater.stop()
                await bot.application.stop()
                await bot.application.shutdown()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

if __name__ == "__main__":
    # Run the main function properly with asyncio
    asyncio.run(main())
