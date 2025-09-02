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
    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.application = ApplicationBuilder().token(BOT_TOKEN).build()
        self.posted_news = self.load_posted_news()

    def load_posted_news(self):
        """Load previously posted news from file"""
        try:
            with open(POSTED_NEWS_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("No existing posted news file found or file is invalid. Creating new tracking.")
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

    async def fetch_article_content(self, session, url):
        """Fetch the full HTML content of a single article page"""
        try:
            headers = self.get_headers()
            async with session.get(url, headers=headers, timeout=30) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logger.warning(f"Failed to fetch article content from {url}, status code: {response.status}")
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching article content: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching article content: {e}")
            logger.error(traceback.format_exc())
            return None

    def extract_summary(self, html_content, source):
        """Extracts a summary from the article's HTML content"""
        if not html_content:
            return None
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        summary_text = None
        
        if source == 'CoinDesk':
            # Try specific selectors for CoinDesk article summaries
            selectors = [
                'p[data-testid="lede"]',  # Primary lead paragraph on CoinDesk
                '.lede',
                '.summary-paragraph',
                'p'  # Fallback to the first paragraph
            ]
            for selector in selectors:
                summary_elem = soup.select_one(selector)
                if summary_elem and summary_elem.text.strip():
                    summary_text = summary_elem.text.strip()
                    break
        elif source == 'CoinTelegraph':
            # Try specific selectors for CoinTelegraph article summaries
            selectors = [
                '.post-content__lead',
                '.post-content_lead',
                '.lead',
                '.article__teaser',
                'p' # Fallback to the first paragraph
            ]
            for selector in selectors:
                summary_elem = soup.select_one(selector)
                if summary_elem and summary_elem.text.strip():
                    summary_text = summary_elem.text.strip()
                    break
        
        # Clean and shorten the summary
        if summary_text:
            summary_text = summary_text.replace('\n', ' ').replace('\t', ' ').strip()
            # Trim to a reasonable length
            if len(summary_text) > 300:
                summary_text = summary_text[:300] + '...'
        
        return summary_text

    async def fetch_coindesk_news(self):
        """Fetch news from CoinDesk"""
        news_items = []
        async with aiohttp.ClientSession() as session:
            try:
                logger.info("Fetching news from CoinDesk...")
                headers = self.get_headers()
                async with session.get("https://www.coindesk.com/tag/bitcoin/", headers=headers, timeout=30) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        articles = soup.select('article')
                        if not articles:
                            articles = soup.select('.article-card, .story-card, .post-card, .featured-post, .story-module, .story, .post, .card')

                        logger.info(f"Found {len(articles)} articles on CoinDesk")

                        for article in articles[:10]:
                            try:
                                title_elem = None
                                for selector in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', '.headline', '.title', '.card-title', '[data-testid="title"]']:
                                    title_elem = article.select_one(selector)
                                    if title_elem and title_elem.text.strip():
                                        break
                                
                                link_elem = None
                                for selector in ['a', 'a.headline-link', '.card a', '[data-testid="title-link"]']:
                                    link_elem = article.select_one(selector)
                                    if link_elem and link_elem.get('href'):
                                        break

                                title = title_elem.text.strip() if title_elem else None
                                link = link_elem.get('href') if link_elem else None
                                if link and not link.startswith('http'):
                                    link = f"https://www.coindesk.com{link}"

                                if title and link and len(title) > 10:
                                    # FETCH SUMMARY FOR EACH ARTICLE
                                    article_html = await self.fetch_article_content(session, link)
                                    summary = self.extract_summary(article_html, 'CoinDesk')

                                    news_items.append({
                                        'title': title,
                                        'link': link,
                                        'source': 'CoinDesk',
                                        'summary': summary
                                    })
                                else:
                                    logger.debug(f"Skipping article with missing/invalid title or link")
                            except Exception as e:
                                logger.error(f"Error processing CoinDesk article: {e}")
                                continue
                    else:
                        logger.warning(f"Failed to fetch from CoinDesk, status code: {response.status}")
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
                headers = self.get_headers()
                async with session.get("https://cointelegraph.com/tags/bitcoin", headers=headers, timeout=30) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        articles = soup.select('.post-card-inline, .post-card, article, .posts-listing__item')

                        if not articles:
                            articles = soup.select('.card, .news-item, .article, .post, .story')

                        logger.info(f"Found {len(articles)} articles on CoinTelegraph")

                        for article in articles[:10]:
                            try:
                                title_elem = None
                                for selector in ['.post-card-inline__title', '.post-card__title', 'h1', 'h2', 'h3', 'h4', '.title', '.headline']:
                                    title_elem = article.select_one(selector)
                                    if title_elem and title_elem.text.strip():
                                        break
                                
                                link_elem = article.select_one('a')

                                title = title_elem.text.strip() if title_elem else None
                                link = link_elem.get('href') if link_elem else None
                                if link and not link.startswith('http'):
                                    link = f"https://cointelegraph.com{link}"

                                if title and link and len(title) > 10:
                                    # FETCH SUMMARY FOR EACH ARTICLE
                                    article_html = await self.fetch_article_content(session, link)
                                    summary = self.extract_summary(article_html, 'CoinTelegraph')
                                    
                                    news_items.append({
                                        'title': title,
                                        'link': link,
                                        'source': 'CoinTelegraph',
                                        'summary': summary
                                    })
                                else:
                                    logger.debug(f"Skipping article with missing/invalid title or link")
                            except Exception as e:
                                logger.error(f"Error processing CoinTelegraph article: {e}")
                                continue
                    else:
                        logger.warning(f"Failed to fetch from CoinTelegraph, status code: {response.status}")
            except aiohttp.ClientError as e:
                logger.error(f"Network error fetching CoinTelegraph news: {e}")
            except Exception as e:
                logger.error(f"Unexpected error fetching CoinTelegraph news: {e}")
                logger.error(traceback.format_exc())
        
        logger.info(f"Retrieved {len(news_items)} news items from CoinTelegraph")
        return news_items

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
                 f"*{news_item['title']}*\n\n"

        if news_item.get('summary'):
            message += f"{news_item['summary']}\n\n"

        message += f"[Read more]({news_item['link']})"

        try:
            await self.application.bot.send_message(
                chat_id=self.channel_id,
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
            self.clean_old_posts()
            coindesk_news = await self.fetch_coindesk_news()
            cointelegraph_news = await self.fetch_cointelegraph_news()
            
            all_news = coindesk_news + cointelegraph_news
            logger.info(f"Total valid news items: {len(all_news)}")

            posts_count = 0
            for news_item in all_news:
                if not self.is_news_posted(news_item):
                    success = await self.post_news_to_channel(news_item)
                    if success:
                        posts_count += 1
                    await asyncio.sleep(2)
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
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return
    
    CHANNEL_ID_STR = os.environ.get("CHANNEL_ID")
    if not CHANNEL_ID_STR:
        logger.error("CHANNEL_ID environment variable is not set!")
        return
    
    try:
        CHANNEL_ID = int(CHANNEL_ID_STR)
    except (ValueError, TypeError):
        logger.error("CHANNEL_ID is not a valid integer. Please check your environment variable.")
        return

    bot = CryptoNewsBot(channel_id=CHANNEL_ID)
    bot.application.add_handler(CommandHandler("checknews", bot.cmd_check_news))
    
    logger.info("Starting bot...")
    
    news_check_task = None
    
    try:
        await bot.application.initialize()
        await bot.application.start()
        await bot.application.updater.start_polling()

        logger.info("Running initial news check...")
        await bot.check_and_post_news()
        
        logger.info("Starting scheduled news checks...")
        news_check_task = asyncio.create_task(bot.scheduled_news_check())

        while True:
            await asyncio.sleep(60)
            
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopping...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
    finally:
        try:
            if news_check_task and not news_check_task.done():
                news_check_task.cancel()
                try:
                    await news_check_task
                except asyncio.CancelledError:
                    pass

            if hasattr(bot, 'application'):
                if hasattr(bot.application, 'updater'):
                    await bot.application.updater.stop()
                await bot.application.stop()
                await bot.application.shutdown()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

if __name__ == "__main__":
    asyncio.run(main())
