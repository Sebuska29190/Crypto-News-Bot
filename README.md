# Crypto News Bot

Crypto News Bot is a Telegram bot that fetches and posts the latest cryptocurrency news from sources like CoinDesk and CoinTelegraph. The bot is designed to automate news updates and deliver them to a specified Telegram channel.

## Features

- Fetches latest cryptocurrency news from CoinDesk and CoinTelegraph.
- Posts news updates to a designated Telegram channel.
- Avoids duplicate news posts by tracking already posted articles.
- Uses rotating User-Agent headers to avoid request blocking.
- Supports manual news check via Telegram command `/checknews`.
- Runs periodic news checks at a configurable interval.

## Requirements

- Python 3.8+
- Telegram Bot API token
- A Telegram channel to post news updates

## Installation

1. Clone the repository:

   ```sh
   git clone https://github.com/thisisryem/Crypto-News-Bot.git
   cd crypto-news-bot
   ```

2. Install dependencies:

   ```sh
   pip install -r requirements.txt
   ```

3. Set up environment variables:

   ```sh
   export BOT_TOKEN='your-telegram-bot-token'
   ```

4. Run the bot:

   ```sh
   python news_bot.py
   ```

## Configuration

- `BOT_TOKEN`: Your Telegram bot's API token (required).
- `CHANNEL_ID`: The Telegram channel where news will be posted (required).
- `NEWS_CHECK_INTERVAL`: Interval (in seconds) for automated news checks. Default is 3600 seconds (1 hour).

## Usage

- **Start the bot**: Run `python news_bot.py`.
- **Check news manually**: Send `/checknews` command in the Telegram bot chat.
- **Stop the bot**: Use `CTRL + C` in the terminal.

## Logging

The bot logs activities such as fetching news, errors, and posted articles. Logs are printed to the console for monitoring and debugging.

## License

This project is licensed under the [GNU GENERAL PUBLIC LICENSE](https://github.com/thisisryem/Crypto-News-Bot/blob/main/LICENSE)

## Contributing

Feel free to open issues or submit pull requests to improve the bot.

## Author

- [Jabir Ahmad Ryem](https://github.com/thisisryem)

- [Instagram](https;//instagram.com/thisisryem)

