"""
Market Data Service - Solana market data and price feeds
"""

import asyncio
from typing import Dict, List, Optional

import grpc
from loguru import logger

from proto import trading_pb2, trading_pb2_grpc
from utils.solana_manager import SolanaManager
from utils.database import DatabaseManager
from utils.redis_client import RedisClient


class MarketDataService(trading_pb2_grpc.MarketDataServiceServicer):
    """Market data service implementation"""
    
    def __init__(self, db_manager: DatabaseManager, redis_client: RedisClient):
        self.db_manager = db_manager
        self.redis_client = redis_client
        self.solana_manager = None  # Will be initialized with settings
        self.running = False
        self.price_subscribers: Dict[str, List] = {}
        
    async def start(self):
        """Start the market data service"""
        self.running = True
        logger.info("✅ Market data service started")
        
    async def stop(self):
        """Stop the market data service"""
        self.running = False
        logger.info("✅ Market data service stopped")
    
    async def GetTokenPrice(self, request: trading_pb2.PriceRequest, context) -> trading_pb2.PriceResponse:
        """Get current token price"""
        try:
            token_mint = request.token_mint
            cluster = request.cluster
            
            # Try to get from cache first
            cache_key = f"price:{token_mint}:{cluster}"
            cached_price = await self.redis_client.get(cache_key)
            
            if cached_price:
                # Parse cached price data
                import json
                price_data = json.loads(cached_price)
                return trading_pb2.PriceResponse(
                    token_mint=token_mint,
                    price=price_data["price"],
                    price_change_24h=price_data["price_change_24h"],
                    volume_24h=price_data["volume_24h"],
                    market_cap=price_data["market_cap"],
                    timestamp=price_data["timestamp"]
                )
            
            # Get fresh price data
            price_data = await self._fetch_token_price(token_mint, cluster)
            
            if price_data["success"]:
                # Cache the price data
                await self.redis_client.set(
                    cache_key,
                    price_data["data"],
                    expire=60  # Cache for 1 minute
                )
                
                return trading_pb2.PriceResponse(
                    token_mint=token_mint,
                    price=price_data["price"],
                    price_change_24h=price_data["price_change_24h"],
                    volume_24h=price_data["volume_24h"],
                    market_cap=price_data["market_cap"],
                    timestamp=price_data["timestamp"]
                )
            else:
                context.abort(grpc.StatusCode.NOT_FOUND, f"Price not found: {price_data['error']}")
                
        except Exception as e:
            logger.error(f"❌ Error getting token price: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def GetTokenInfo(self, request: trading_pb2.TokenInfoRequest, context) -> trading_pb2.TokenInfo:
        """Get token information"""
        try:
            token_mint = request.token_mint
            cluster = request.cluster
            
            # Try to get from cache first
            cache_key = f"token_info:{token_mint}:{cluster}"
            cached_info = await self.redis_client.get(cache_key)
            
            if cached_info:
                # Parse cached token info
                import json
                token_data = json.loads(cached_info)
                return trading_pb2.TokenInfo(
                    token_mint=token_mint,
                    name=token_data["name"],
                    symbol=token_data["symbol"],
                    decimals=token_data["decimals"],
                    total_supply=token_data["total_supply"],
                    circulating_supply=token_data["circulating_supply"],
                    mint_authority=token_data["mint_authority"],
                    is_verified=token_data["is_verified"],
                    liquidity=token_data["liquidity"],
                    holders_count=token_data["holders_count"]
                )
            
            # Get fresh token info
            token_info = await self.solana_manager.get_token_info(token_mint)
            
            if token_info["success"]:
                # Cache the token info
                await self.redis_client.set(
                    cache_key,
                    token_info["data"],
                    expire=300  # Cache for 5 minutes
                )
                
                return trading_pb2.TokenInfo(
                    token_mint=token_mint,
                    name=token_info["name"],
                    symbol=token_info["symbol"],
                    decimals=token_info["decimals"],
                    total_supply=token_info["total_supply"],
                    circulating_supply=token_info["circulating_supply"],
                    mint_authority=token_info["mint_authority"],
                    is_verified=token_info["is_verified"],
                    liquidity=token_info["liquidity"],
                    holders_count=token_info["holders_count"]
                )
            else:
                context.abort(grpc.StatusCode.NOT_FOUND, f"Token not found: {token_info['error']}")
                
        except Exception as e:
            logger.error(f"❌ Error getting token info: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def GetMarketData(self, request: trading_pb2.MarketDataRequest, context) -> trading_pb2.MarketData:
        """Get market data for multiple tokens"""
        try:
            cluster = request.cluster
            token_mints = request.token_mints
            
            prices = []
            total_volume = 0.0
            total_market_cap = 0.0
            
            for token_mint in token_mints:
                price_data = await self._fetch_token_price(token_mint, cluster)
                
                if price_data["success"]:
                    price_response = trading_pb2.PriceResponse(
                        token_mint=token_mint,
                        price=price_data["price"],
                        price_change_24h=price_data["price_change_24h"],
                        volume_24h=price_data["volume_24h"],
                        market_cap=price_data["market_cap"],
                        timestamp=price_data["timestamp"]
                    )
                    prices.append(price_response)
                    
                    total_volume += price_data["volume_24h"]
                    total_market_cap += price_data["market_cap"]
            
            return trading_pb2.MarketData(
                cluster=cluster,
                prices=prices,
                total_volume_24h=total_volume,
                total_market_cap=total_market_cap,
                timestamp=int(asyncio.get_event_loop().time())
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting market data: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def SubscribeToPriceUpdates(self, request: trading_pb2.PriceSubscription, context):
        """Subscribe to real-time price updates"""
        try:
            token_mint = request.token_mint
            cluster = request.cluster
            update_interval = request.update_interval
            
            logger.info(f"📡 Starting price subscription for {token_mint}")
            
            # Add to subscribers
            subscription_key = f"{token_mint}:{cluster}"
            if subscription_key not in self.price_subscribers:
                self.price_subscribers[subscription_key] = []
            self.price_subscribers[subscription_key].append(context)
            
            try:
                while self.running and context.is_active():
                    # Get current price
                    price_data = await self._fetch_token_price(token_mint, cluster)
                    
                    if price_data["success"]:
                        price_update = trading_pb2.PriceUpdate(
                            token_mint=token_mint,
                            price=price_data["price"],
                            price_change=price_data["price_change_24h"],
                            timestamp=price_data["timestamp"]
                        )
                        
                        yield price_update
                    
                    # Wait for next update
                    await asyncio.sleep(update_interval)
                    
            except Exception as e:
                logger.error(f"❌ Error in price subscription: {e}")
            finally:
                # Remove from subscribers
                if subscription_key in self.price_subscribers:
                    if context in self.price_subscribers[subscription_key]:
                        self.price_subscribers[subscription_key].remove(context)
                
                logger.info(f"📡 Stopped price subscription for {token_mint}")
                
        except Exception as e:
            logger.error(f"❌ Error setting up price subscription: {e}")
    
    async def GetPriorityFee(self, request: trading_pb2.PriorityFeeRequest, context) -> trading_pb2.PriorityFeeResponse:
        """Get current priority fees"""
        try:
            cluster = request.cluster
            
            # Get priority fees from Solana
            priority_fees = await self.solana_manager.get_priority_fee()
            
            return trading_pb2.PriorityFeeResponse(
                cluster=cluster,
                slow_priority_fee=priority_fees["slow_priority_fee"],
                standard_priority_fee=priority_fees["standard_priority_fee"],
                fast_priority_fee=priority_fees["fast_priority_fee"],
                instant_priority_fee=priority_fees["instant_priority_fee"],
                timestamp=int(asyncio.get_event_loop().time())
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting priority fee: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def _fetch_token_price(self, token_mint: str, cluster: int) -> Dict:
        """Fetch token price from various sources"""
        try:
            # Try Jupiter API first
            jupiter_price = await self._get_jupiter_price(token_mint)
            if jupiter_price["success"]:
                return jupiter_price
            
            # Try Raydium API
            raydium_price = await self._get_raydium_price(token_mint)
            if raydium_price["success"]:
                return raydium_price
            
            # Try direct Solana RPC
            solana_price = await self._get_solana_price(token_mint)
            if solana_price["success"]:
                return solana_price
            
            return {
                "success": False,
                "error": "Price not available from any source"
            }
            
        except Exception as e:
            logger.error(f"❌ Error fetching token price: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _get_jupiter_price(self, token_mint: str) -> Dict:
        """Get price from Jupiter API"""
        try:
            import aiohttp
            
            # SOL mint address for comparison
            sol_mint = "So11111111111111111111111111111111111111112"
            
            async with aiohttp.ClientSession() as session:
                url = "https://price.jup.ag/v4/price"
                params = {
                    "ids": token_mint,
                    "vsToken": sol_mint
                }
                
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if token_mint in data.get("data", {}):
                            price_data = data["data"][token_mint]
                            
                            return {
                                "success": True,
                                "price": price_data.get("price", 0.0),
                                "price_change_24h": price_data.get("priceChange24h", 0.0),
                                "volume_24h": price_data.get("volume24h", 0.0),
                                "market_cap": price_data.get("marketCap", 0.0),
                                "timestamp": int(asyncio.get_event_loop().time()),
                                "data": {
                                    "price": price_data.get("price", 0.0),
                                    "price_change_24h": price_data.get("priceChange24h", 0.0),
                                    "volume_24h": price_data.get("volume24h", 0.0),
                                    "market_cap": price_data.get("marketCap", 0.0),
                                    "timestamp": int(asyncio.get_event_loop().time())
                                }
                            }
            
            return {"success": False, "error": "Jupiter price not available"}
            
        except Exception as e:
            logger.error(f"❌ Error getting Jupiter price: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_raydium_price(self, token_mint: str) -> Dict:
        """Get price from Raydium API"""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = "https://api.raydium.io/v2/main/price"
                
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if token_mint in data:
                            price_data = data[token_mint]
                            
                            return {
                                "success": True,
                                "price": price_data.get("price", 0.0),
                                "price_change_24h": price_data.get("priceChange24h", 0.0),
                                "volume_24h": price_data.get("volume24h", 0.0),
                                "market_cap": price_data.get("marketCap", 0.0),
                                "timestamp": int(asyncio.get_event_loop().time()),
                                "data": {
                                    "price": price_data.get("price", 0.0),
                                    "price_change_24h": price_data.get("priceChange24h", 0.0),
                                    "volume_24h": price_data.get("volume24h", 0.0),
                                    "market_cap": price_data.get("marketCap", 0.0),
                                    "timestamp": int(asyncio.get_event_loop().time())
                                }
                            }
            
            return {"success": False, "error": "Raydium price not available"}
            
        except Exception as e:
            logger.error(f"❌ Error getting Raydium price: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_solana_price(self, token_mint: str) -> Dict:
        """Get price from Solana RPC"""
        try:
            # This would use Solana RPC to get token price
            # For now, return placeholder
            return {
                "success": True,
                "price": 0.0,
                "price_change_24h": 0.0,
                "volume_24h": 0.0,
                "market_cap": 0.0,
                "timestamp": int(asyncio.get_event_loop().time()),
                "data": {
                    "price": 0.0,
                    "price_change_24h": 0.0,
                    "volume_24h": 0.0,
                    "market_cap": 0.0,
                    "timestamp": int(asyncio.get_event_loop().time())
                }
            }
        except Exception as e:
            logger.error(f"❌ Error getting Solana price: {e}")
            return {"success": False, "error": str(e)} 