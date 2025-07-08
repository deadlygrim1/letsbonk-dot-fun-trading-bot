#!/usr/bin/env python3
"""
LetsBonkDotFun Trading Bot - Main Entry Point
Super fastest trading bot with sniper and copy trading capabilities
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import List

import grpc
from loguru import logger

from config.settings import Settings
from services.trading_service import TradingService
from services.sniper_service import SniperService
from services.copy_trade_service import CopyTradeService
from services.market_data_service import MarketDataService
from utils.grpc_server import GRPCServer
from utils.database import DatabaseManager
from utils.redis_client import RedisClient


class TradingBot:
    """Main trading bot application class"""
    
    def __init__(self):
        self.settings = Settings()
        self.grpc_server = None
        self.services: List = []
        self.running = False
        
        # Initialize components
        self.db_manager = DatabaseManager(self.settings.database_url)
        self.redis_client = RedisClient(self.settings.redis_url)
        
        # Initialize services
        self.trading_service = TradingService(self.db_manager, self.redis_client)
        self.sniper_service = SniperService(self.db_manager, self.redis_client)
        self.copy_trade_service = CopyTradeService(self.db_manager, self.redis_client)
        self.market_data_service = MarketDataService(self.db_manager, self.redis_client)
        
        # Add services to list
        self.services.extend([
            self.trading_service,
            self.sniper_service,
            self.copy_trade_service,
            self.market_data_service
        ])
    
    async def start(self):
        """Start the trading bot"""
        try:
            logger.info("🚀 Starting LetsBonkDotFun Trading Bot...")
            
            # Initialize database
            await self.db_manager.initialize()
            logger.info("✅ Database initialized")
            
            # Initialize Redis
            await self.redis_client.initialize()
            logger.info("✅ Redis initialized")
            
            # Start all services
            for service in self.services:
                await service.start()
                logger.info(f"✅ {service.__class__.__name__} started")
            
            # Start gRPC server
            self.grpc_server = GRPCServer(
                host=self.settings.grpc_host,
                port=self.settings.grpc_port
            )
            
            # Add services to gRPC server
            self.grpc_server.add_service(self.trading_service)
            self.grpc_server.add_service(self.sniper_service)
            self.grpc_server.add_service(self.copy_trade_service)
            self.grpc_server.add_service(self.market_data_service)
            
            # Start gRPC server
            await self.grpc_server.start()
            logger.info(f"✅ gRPC server started on {self.settings.grpc_host}:{self.settings.grpc_port}")
            
            self.running = True
            logger.info("🎉 LetsBonkDotFun Trading Bot is running!")
            
            # Keep the application running
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Failed to start trading bot: {e}")
            await self.stop()
            sys.exit(1)
    
    async def stop(self):
        """Stop the trading bot"""
        logger.info("🛑 Stopping LetsBonkDotFun Trading Bot...")
        self.running = False
        
        # Stop gRPC server
        if self.grpc_server:
            await self.grpc_server.stop()
            logger.info("✅ gRPC server stopped")
        
        # Stop all services
        for service in self.services:
            await service.stop()
            logger.info(f"✅ {service.__class__.__name__} stopped")
        
        # Close database connection
        await self.db_manager.close()
        logger.info("✅ Database connection closed")
        
        # Close Redis connection
        await self.redis_client.close()
        logger.info("✅ Redis connection closed")
        
        logger.info("👋 LetsBonkDotFun Trading Bot stopped")


async def main():
    """Main function"""
    # Setup logging
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )
    logger.add(
        "logs/trading_bot.log",
        rotation="1 day",
        retention="30 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG"
    )
    
    # Create logs directory if it doesn't exist
    Path("logs").mkdir(exist_ok=True)
    
    # Create trading bot instance
    bot = TradingBot()
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        asyncio.create_task(bot.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        await bot.stop()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await bot.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 