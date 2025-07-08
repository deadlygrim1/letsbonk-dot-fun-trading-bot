"""
Copy Trading Service - Real-time signal copying from top Solana traders
"""

import asyncio
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import grpc
from loguru import logger

from proto import trading_pb2, trading_pb2_grpc
from utils.solana_manager import SolanaManager
from utils.database import DatabaseManager
from utils.redis_client import RedisClient


class CopyTradeService(trading_pb2_grpc.CopyTradeServiceServicer):
    """Copy trading service implementation"""
    
    def __init__(self, db_manager: DatabaseManager, redis_client: RedisClient):
        self.db_manager = db_manager
        self.redis_client = redis_client
        self.solana_manager = None  # Will be initialized with settings
        self.running = False
        self.active_copy_traders: Dict[str, Dict] = {}
        self.monitoring_task = None
        
    async def start(self):
        """Start the copy trading service"""
        self.running = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("✅ Copy trading service started")
        
    async def stop(self):
        """Stop the copy trading service"""
        self.running = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
        logger.info("✅ Copy trading service stopped")
    
    async def StartCopyTrading(self, request: trading_pb2.CopyTradeConfig, context) -> trading_pb2.CopyTradeResponse:
        """Start copy trading"""
        try:
            logger.info(f"📋 Starting copy trading from {request.source_wallet} to {request.target_wallet}")
            
            copy_trade_id = str(uuid.uuid4())
            
            # Validate configuration
            if not self._validate_wallet_address(request.source_wallet):
                return trading_pb2.CopyTradeResponse(
                    success=False,
                    message="Invalid source wallet address"
                )
            
            if not self._validate_wallet_address(request.target_wallet):
                return trading_pb2.CopyTradeResponse(
                    success=False,
                    message="Invalid target wallet address"
                )
            
            # Create copy trading instance
            copy_trade_config = {
                "copy_trade_id": copy_trade_id,
                "source_wallet": request.source_wallet,
                "target_wallet": request.target_wallet,
                "private_key": request.private_key,
                "allocation_percentage": request.allocation_percentage,
                "max_position_size": request.max_position_size,
                "min_trade_amount": request.min_trade_amount,
                "max_trades_per_hour": request.max_trades_per_hour,
                "cluster": request.cluster,
                "rpc_url": request.rpc_url,
                "start_time": datetime.now().timestamp(),
                "is_running": True,
                "copied_trades": 0,
                "total_profit": 0.0,
                "trades_this_hour": 0,
                "last_trade_time": 0
            }
            
            # Store copy trading configuration
            await self._store_copy_trade_config(copy_trade_config)
            
            # Add to active copy traders
            self.active_copy_traders[copy_trade_id] = copy_trade_config
            
            logger.info(f"✅ Copy trading started successfully: {copy_trade_id}")
            
            return trading_pb2.CopyTradeResponse(
                success=True,
                message="Copy trading started successfully",
                copy_trade_id=copy_trade_id
            )
            
        except Exception as e:
            logger.error(f"❌ Error starting copy trading: {e}")
            return trading_pb2.CopyTradeResponse(
                success=False,
                message=f"Failed to start copy trading: {str(e)}"
            )
    
    async def StopCopyTrading(self, request: trading_pb2.CopyTradeRequest, context) -> trading_pb2.CopyTradeResponse:
        """Stop copy trading"""
        try:
            copy_trade_id = request.copy_trade_id
            
            if copy_trade_id not in self.active_copy_traders:
                return trading_pb2.CopyTradeResponse(
                    success=False,
                    message="Copy trading instance not found"
                )
            
            # Stop copy trading
            self.active_copy_traders[copy_trade_id]["is_running"] = False
            del self.active_copy_traders[copy_trade_id]
            
            logger.info(f"✅ Copy trading stopped: {copy_trade_id}")
            
            return trading_pb2.CopyTradeResponse(
                success=True,
                message="Copy trading stopped successfully"
            )
            
        except Exception as e:
            logger.error(f"❌ Error stopping copy trading: {e}")
            return trading_pb2.CopyTradeResponse(
                success=False,
                message=f"Failed to stop copy trading: {str(e)}"
            )
    
    async def GetCopyTradeStatus(self, request: trading_pb2.CopyTradeRequest, context) -> trading_pb2.CopyTradeStatus:
        """Get copy trading status"""
        try:
            copy_trade_id = request.copy_trade_id
            
            if copy_trade_id not in self.active_copy_traders:
                context.abort(grpc.StatusCode.NOT_FOUND, "Copy trading instance not found")
            
            copy_trade_config = self.active_copy_traders[copy_trade_id]
            
            return trading_pb2.CopyTradeStatus(
                copy_trade_id=copy_trade_id,
                is_running=copy_trade_config["is_running"],
                source_wallet=copy_trade_config["source_wallet"],
                target_wallet=copy_trade_config["target_wallet"],
                copied_trades=copy_trade_config["copied_trades"],
                total_profit=copy_trade_config["total_profit"],
                allocation_percentage=copy_trade_config["allocation_percentage"],
                start_time=int(copy_trade_config["start_time"])
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting copy trade status: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def AddTraderToCopy(self, request: trading_pb2.TraderConfig, context) -> trading_pb2.CopyTradeResponse:
        """Add trader to copy"""
        try:
            copy_trade_id = request.copy_trade_id
            source_wallet = request.source_wallet
            
            if copy_trade_id not in self.active_copy_traders:
                return trading_pb2.CopyTradeResponse(
                    success=False,
                    message="Copy trading instance not found"
                )
            
            if not self._validate_wallet_address(source_wallet):
                return trading_pb2.CopyTradeResponse(
                    success=False,
                    message="Invalid source wallet address"
                )
            
            # Add trader to copy
            self.active_copy_traders[copy_trade_id]["source_wallet"] = source_wallet
            self.active_copy_traders[copy_trade_id]["allocation_percentage"] = request.allocation_percentage
            
            logger.info(f"✅ Added trader {source_wallet} to copy trading {copy_trade_id}")
            
            return trading_pb2.CopyTradeResponse(
                success=True,
                message="Trader added successfully"
            )
            
        except Exception as e:
            logger.error(f"❌ Error adding trader: {e}")
            return trading_pb2.CopyTradeResponse(
                success=False,
                message=f"Failed to add trader: {str(e)}"
            )
    
    async def RemoveTraderToCopy(self, request: trading_pb2.TraderConfig, context) -> trading_pb2.CopyTradeResponse:
        """Remove trader from copy"""
        try:
            copy_trade_id = request.copy_trade_id
            
            if copy_trade_id not in self.active_copy_traders:
                return trading_pb2.CopyTradeResponse(
                    success=False,
                    message="Copy trading instance not found"
                )
            
            # Stop copy trading for this instance
            self.active_copy_traders[copy_trade_id]["is_running"] = False
            
            logger.info(f"✅ Removed trader from copy trading {copy_trade_id}")
            
            return trading_pb2.CopyTradeResponse(
                success=True,
                message="Trader removed successfully"
            )
            
        except Exception as e:
            logger.error(f"❌ Error removing trader: {e}")
            return trading_pb2.CopyTradeResponse(
                success=False,
                message=f"Failed to remove trader: {str(e)}"
            )
    
    async def GetCopyTradeHistory(self, request: trading_pb2.CopyTradeRequest, context) -> trading_pb2.CopyTradeHistory:
        """Get copy trading history"""
        try:
            copy_trade_id = request.copy_trade_id
            
            # Get history from database
            records = await self._get_copy_trade_history(copy_trade_id)
            
            copy_trade_records = []
            for record in records:
                copy_trade_record = trading_pb2.CopyTradeRecord(
                    copy_trade_id=record["copy_trade_id"],
                    source_wallet=record["source_wallet"],
                    target_wallet=record["target_wallet"],
                    token_mint=record["token_mint"],
                    amount=record["amount"],
                    order_type=record["order_type"],
                    profit=record["profit"],
                    timestamp=int(record["timestamp"]),
                    signature=record["signature"],
                    success=record["success"]
                )
                copy_trade_records.append(copy_trade_record)
            
            return trading_pb2.CopyTradeHistory(
                records=copy_trade_records,
                total_count=len(copy_trade_records)
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting copy trade history: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def _monitoring_loop(self):
        """Main monitoring loop for copy trading"""
        logger.info("📋 Starting copy trading monitoring loop")
        
        while self.running:
            try:
                # Monitor active copy traders
                await self._monitor_copy_traders()
                
                # Sleep for monitoring interval
                await asyncio.sleep(1)  # Check every second
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in copy trading monitoring loop: {e}")
                await asyncio.sleep(5)
        
        logger.info("📋 Copy trading monitoring loop stopped")
    
    async def _monitor_copy_traders(self):
        """Monitor active copy traders"""
        try:
            for copy_trade_id, copy_trade_config in self.active_copy_traders.items():
                if not copy_trade_config["is_running"]:
                    continue
                
                # Check for new trades from source wallet
                await self._check_source_wallet_trades(copy_trade_id, copy_trade_config)
                
        except Exception as e:
            logger.error(f"❌ Error monitoring copy traders: {e}")
    
    async def _check_source_wallet_trades(self, copy_trade_id: str, copy_trade_config: Dict):
        """Check for new trades from source wallet"""
        try:
            source_wallet = copy_trade_config["source_wallet"]
            
            # Get recent transactions from source wallet
            recent_trades = await self._get_recent_trades(source_wallet)
            
            for trade in recent_trades:
                # Check if we should copy this trade
                if await self._should_copy_trade(copy_trade_id, trade):
                    await self._copy_trade(copy_trade_id, copy_trade_config, trade)
                    
        except Exception as e:
            logger.error(f"❌ Error checking source wallet trades: {e}")
    
    async def _get_recent_trades(self, wallet_address: str) -> List[Dict]:
        """Get recent trades from wallet"""
        try:
            # This would query Solana for recent transactions
            # For now, return empty list
            return []
        except Exception as e:
            logger.error(f"❌ Error getting recent trades: {e}")
            return []
    
    async def _should_copy_trade(self, copy_trade_id: str, trade: Dict) -> bool:
        """Check if trade should be copied"""
        try:
            copy_trade_config = self.active_copy_traders[copy_trade_id]
            
            # Check if trade is recent enough
            trade_time = trade.get("timestamp", 0)
            last_trade_time = copy_trade_config.get("last_trade_time", 0)
            
            if trade_time <= last_trade_time:
                return False
            
            # Check hourly trade limit
            current_time = datetime.now().timestamp()
            if current_time - last_trade_time < 3600:  # 1 hour
                if copy_trade_config["trades_this_hour"] >= copy_trade_config["max_trades_per_hour"]:
                    return False
            else:
                # Reset hourly counter
                copy_trade_config["trades_this_hour"] = 0
            
            # Check minimum trade amount
            trade_amount = trade.get("amount", 0)
            if trade_amount < copy_trade_config["min_trade_amount"]:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error checking if trade should be copied: {e}")
            return False
    
    async def _copy_trade(self, copy_trade_id: str, copy_trade_config: Dict, trade: Dict):
        """Copy a trade"""
        try:
            logger.info(f"📋 Copying trade from {trade.get('signature', 'unknown')}")
            
            # Calculate copy amount based on allocation
            original_amount = trade.get("amount", 0)
            copy_amount = original_amount * copy_trade_config["allocation_percentage"]
            
            # Check position size limit
            if copy_amount > copy_trade_config["max_position_size"]:
                copy_amount = copy_trade_config["max_position_size"]
            
            # Execute copy trade
            trade_result = await self.solana_manager.execute_swap(
                token_mint=trade.get("token_mint", ""),
                amount=copy_amount,
                slippage=0.05,  # 5% slippage
                wallet_address=copy_trade_config["target_wallet"],
                private_key=copy_trade_config["private_key"],
                is_sell=(trade.get("order_type", 0) == 1)  # SELL
            )
            
            if trade_result["success"]:
                # Record successful copy trade
                await self._record_copy_trade(
                    copy_trade_id=copy_trade_id,
                    source_wallet=copy_trade_config["source_wallet"],
                    target_wallet=copy_trade_config["target_wallet"],
                    token_mint=trade.get("token_mint", ""),
                    amount=copy_amount,
                    order_type=trade.get("order_type", 0),
                    signature=trade_result["signature"],
                    success=True
                )
                
                # Update copy trading stats
                copy_trade_config["copied_trades"] += 1
                copy_trade_config["trades_this_hour"] += 1
                copy_trade_config["last_trade_time"] = datetime.now().timestamp()
                
                logger.info(f"✅ Trade copied successfully: {trade_result['signature']}")
            else:
                # Record failed copy trade
                await self._record_copy_trade(
                    copy_trade_id=copy_trade_id,
                    source_wallet=copy_trade_config["source_wallet"],
                    target_wallet=copy_trade_config["target_wallet"],
                    token_mint=trade.get("token_mint", ""),
                    amount=copy_amount,
                    order_type=trade.get("order_type", 0),
                    signature="",
                    success=False
                )
                
                logger.error(f"❌ Failed to copy trade: {trade_result['error']}")
                
        except Exception as e:
            logger.error(f"❌ Error copying trade: {e}")
    
    def _validate_wallet_address(self, wallet_address: str) -> bool:
        """Validate Solana wallet address"""
        try:
            # Basic validation for Solana address format
            if len(wallet_address) != 44:  # Base58 encoded Solana address length
                return False
            
            # Check if it's a valid base58 string
            import base58
            base58.b58decode(wallet_address)
            return True
            
        except Exception:
            return False
    
    # Database operations
    async def _store_copy_trade_config(self, config: Dict):
        """Store copy trading configuration in database"""
        try:
            await self.db_manager.execute(
                """
                INSERT INTO copy_traders (
                    copy_trade_id, source_wallet, target_wallet, allocation_percentage,
                    max_position_size, min_trade_amount, max_trades_per_hour,
                    cluster, rpc_url, start_time, is_running
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                (
                    config["copy_trade_id"], config["source_wallet"], config["target_wallet"],
                    config["allocation_percentage"], config["max_position_size"],
                    config["min_trade_amount"], config["max_trades_per_hour"],
                    config["cluster"], config["rpc_url"], config["start_time"], config["is_running"]
                )
            )
        except Exception as e:
            logger.error(f"❌ Error storing copy trade config: {e}")
            raise
    
    async def _record_copy_trade(self, copy_trade_id: str, source_wallet: str, target_wallet: str,
                                token_mint: str, amount: float, order_type: int, signature: str, success: bool):
        """Record copy trade in database"""
        try:
            await self.db_manager.execute(
                """
                INSERT INTO copy_trade_records (
                    copy_trade_id, source_wallet, target_wallet, token_mint,
                    amount, order_type, signature, timestamp, success
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                (
                    copy_trade_id, source_wallet, target_wallet, token_mint,
                    amount, order_type, signature, datetime.now().timestamp(), success
                )
            )
        except Exception as e:
            logger.error(f"❌ Error recording copy trade: {e}")
            raise
    
    async def _get_copy_trade_history(self, copy_trade_id: str) -> List[Dict]:
        """Get copy trading history from database"""
        try:
            results = await self.db_manager.fetch_all(
                "SELECT * FROM copy_trade_records WHERE copy_trade_id = $1 ORDER BY timestamp DESC",
                (copy_trade_id,)
            )
            return results
        except Exception as e:
            logger.error(f"❌ Error getting copy trade history: {e}")
            return [] 