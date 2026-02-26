import os
import asyncio
import logging
import sys
from datetime import datetime

# Create logs folder first
os.makedirs("logs", exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'logs/bot_{datetime.now().strftime("%Y%m%d")}.log')
    ]
)

logger = logging.getLogger(__name__)

from config import config
from database import db
from bot import bot

async def main():
    try:
        # Initialize database ONCE
        await db.initialize()
        
        # Start bot
        await bot.start(config.DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"❌ Failed to start: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
