"""
Sniper Service - Ultra-fast SPL token detection and automatic sniping
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


class SniperService(trading_pb2_grpc.SniperServiceServicer):
    """Sniper service implementation"""
    
    def __init__(self, db_manager: DatabaseManager, redis_client: RedisClient):
        self.db_manager = db_manager
        self.redis_client = redis_client
        self.solana_manager = None  # Will be initialized with settings
        self.running = False
        self.active_snipers: Dict[str, Dict] = {}
        self.scanning_task = None
        
    async def start(self):
        """Start the sniper service"""
        self.running = True
        self.scanning_task = asyncio.create_task(self._token_scanning_loop())
        logger.info("✅ Sniper service started")
        
    async def stop(self):
        """Stop the sniper service"""
        self.running = False
        if self.scanning_task:
            self.scanning_task.cancel()
        logger.info("✅ Sniper service stopped")
    
    async def StartSniper(self, request: trading_pb2.SniperConfig, context) -> trading_pb2.SniperResponse:
        """Start a new sniper instance"""
        try:
            logger.info(f"🎯 Starting sniper for wallet: {request.wallet_address}")
            
            sniper_id = str(uuid.uuid4())
            
            # Validate configuration
            if not self._validate_wallet_address(request.wallet_address):
                return trading_pb2.SniperResponse(
                    success=False,
                    message="Invalid wallet address"
                )
            
            # Create sniper instance
            sniper_config = {
                "sniper_id": sniper_id,
                "wallet_address": request.wallet_address,
                "private_key": request.private_key,
                "target_tokens": list(request.target_tokens),
                "buy_amount": request.buy_amount,
                "max_slippage": request.max_slippage,
                "profit_target": request.profit_target,
                "stop_loss": request.stop_loss,
                "auto_sell": request.auto_sell,
                "compute_unit_limit": request.compute_unit_limit,
                "cluster": request.cluster,
                "rpc_url": request.rpc_url,
                "start_time": datetime.now().timestamp(),
                "is_running": True,
                "successful_snipes": 0,
                "failed_snipes": 0,
                "total_profit": 0.0
            }
            
            # Store sniper configuration
            await self._store_sniper_config(sniper_config)
            
            # Add to active snipers
            self.active_snipers[sniper_id] = sniper_config
            
            logger.info(f"✅ Sniper started successfully: {sniper_id}")
            
            return trading_pb2.SniperResponse(
                success=True,
                message="Sniper started successfully",
                sniper_id=sniper_id
            )
            
        except Exception as e:
            logger.error(f"❌ Error starting sniper: {e}")
            return trading_pb2.SniperResponse(
                success=False,
                message=f"Failed to start sniper: {str(e)}"
            )
    
    async def StopSniper(self, request: trading_pb2.SniperRequest, context) -> trading_pb2.SniperResponse:
        """Stop a sniper instance"""
        try:
            sniper_id = request.sniper_id
            
            if sniper_id not in self.active_snipers:
                return trading_pb2.SniperResponse(
                    success=False,
                    message="Sniper not found"
                )
            
            # Stop sniper
            self.active_snipers[sniper_id]["is_running"] = False
            del self.active_snipers[sniper_id]
            
            logger.info(f"✅ Sniper stopped: {sniper_id}")
            
            return trading_pb2.SniperResponse(
                success=True,
                message="Sniper stopped successfully"
            )
            
        except Exception as e:
            logger.error(f"❌ Error stopping sniper: {e}")
            return trading_pb2.SniperResponse(
                success=False,
                message=f"Failed to stop sniper: {str(e)}"
            )
    
    async def GetSniperStatus(self, request: trading_pb2.SniperRequest, context) -> trading_pb2.SniperStatus:
        """Get sniper status"""
        try:
            sniper_id = request.sniper_id
            
            if sniper_id not in self.active_snipers:
                context.abort(grpc.StatusCode.NOT_FOUND, "Sniper not found")
            
            sniper_config = self.active_snipers[sniper_id]
            
            return trading_pb2.SniperStatus(
                sniper_id=sniper_id,
                is_running=sniper_config["is_running"],
                active_targets=sniper_config["target_tokens"],
                successful_snipes=sniper_config["successful_snipes"],
                failed_snipes=sniper_config["failed_snipes"],
                total_profit=sniper_config["total_profit"],
                start_time=int(sniper_config["start_time"])
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting sniper status: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def AddTargetToken(self, request: trading_pb2.TokenTarget, context) -> trading_pb2.SniperResponse:
        """Add target token to sniper"""
        try:
            sniper_id = request.sniper_id
            token_mint = request.token_mint
            
            if sniper_id not in self.active_snipers:
                return trading_pb2.SniperResponse(
                    success=False,
                    message="Sniper not found"
                )
            
            if not self._validate_token_mint(token_mint):
                return trading_pb2.SniperResponse(
                    success=False,
                    message="Invalid token mint address"
                )
            
            # Add to target tokens
            self.active_snipers[sniper_id]["target_tokens"].append(token_mint)
            
            logger.info(f"✅ Added target token {token_mint} to sniper {sniper_id}")
            
            return trading_pb2.SniperResponse(
                success=True,
                message="Target token added successfully"
            )
            
        except Exception as e:
            logger.error(f"❌ Error adding target token: {e}")
            return trading_pb2.SniperResponse(
                success=False,
                message=f"Failed to add target token: {str(e)}"
            )
    
    async def RemoveTargetToken(self, request: trading_pb2.TokenTarget, context) -> trading_pb2.SniperResponse:
        """Remove target token from sniper"""
        try:
            sniper_id = request.sniper_id
            token_mint = request.token_mint
            
            if sniper_id not in self.active_snipers:
                return trading_pb2.SniperResponse(
                    success=False,
                    message="Sniper not found"
                )
            
            # Remove from target tokens
            if token_mint in self.active_snipers[sniper_id]["target_tokens"]:
                self.active_snipers[sniper_id]["target_tokens"].remove(token_mint)
            
            logger.info(f"✅ Removed target token {token_mint} from sniper {sniper_id}")
            
            return trading_pb2.SniperResponse(
                success=True,
                message="Target token removed successfully"
            )
            
        except Exception as e:
            logger.error(f"❌ Error removing target token: {e}")
            return trading_pb2.SniperResponse(
                success=False,
                message=f"Failed to remove target token: {str(e)}"
            )
    
    async def GetSniperHistory(self, request: trading_pb2.SniperRequest, context) -> trading_pb2.SniperHistory:
        """Get sniper history"""
        try:
            sniper_id = request.sniper_id
            
            # Get history from database
            records = await self._get_sniper_history(sniper_id)
            
            snipe_records = []
            for record in records:
                snipe_record = trading_pb2.SnipeRecord(
                    sniper_id=record["sniper_id"],
                    token_mint=record["token_mint"],
                    buy_amount=record["buy_amount"],
                    buy_price=record["buy_price"],
                    sell_price=record["sell_price"],
                    profit=record["profit"],
                    profit_percentage=record["profit_percentage"],
                    buy_time=int(record["buy_time"]),
                    sell_time=int(record["sell_time"]),
                    buy_signature=record["buy_signature"],
                    sell_signature=record["sell_signature"],
                    success=record["success"]
                )
                snipe_records.append(snipe_record)
            
            return trading_pb2.SniperHistory(
                records=snipe_records,
                total_count=len(snipe_records)
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting sniper history: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def _token_scanning_loop(self):
        """Main token scanning loop"""
        logger.info("🔍 Starting SPL token scanning loop")
        
        while self.running:
            try:
                # Scan for new tokens and price movements
                await self._scan_for_opportunities()
                
                # Sleep for ultra-fast scanning
                await asyncio.sleep(0.1)  # 100ms interval
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in token scanning loop: {e}")
                await asyncio.sleep(1)
        
        logger.info("🔍 SPL token scanning loop stopped")
    
    async def _scan_for_opportunities(self):
        """Scan for trading opportunities"""
        try:
            # Check active snipers
            for sniper_id, sniper_config in self.active_snipers.items():
                if not sniper_config["is_running"]:
                    continue
                
                # Check target tokens
                for token_mint in sniper_config["target_tokens"]:
                    await self._check_token_opportunity(sniper_id, token_mint)
                    
        except Exception as e:
            logger.error(f"❌ Error scanning for opportunities: {e}")
    
    async def _check_token_opportunity(self, sniper_id: str, token_mint: str):
        """Check if token presents an opportunity"""
        try:
            # Get token price and liquidity
            token_info = await self.solana_manager.get_token_info(token_mint)
            
            if token_info and self._is_good_opportunity(token_info):
                await self._execute_snipe(sniper_id, token_mint, token_info)
                
        except Exception as e:
            logger.error(f"❌ Error checking token opportunity: {e}")
    
    def _is_good_opportunity(self, token_info: Dict) -> bool:
        """Check if token is a good opportunity"""
        try:
            # Check liquidity
            if token_info.get("liquidity", 0) < 1000:  # Less than 1000 USD liquidity
                return False
            
            # Check if token is verified
            if not token_info.get("is_verified", False):
                return False
            
            # Check if token is not a honeypot
            if token_info.get("is_honeypot", False):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error checking opportunity: {e}")
            return False
    
    async def _execute_snipe(self, sniper_id: str, token_mint: str, token_info: Dict):
        """Execute a snipe"""
        try:
            sniper_config = self.active_snipers[sniper_id]
            
            logger.info(f"🎯 Executing snipe for {sniper_id} on {token_mint}")
            
            # Build and send transaction
            tx_result = await self.solana_manager.execute_swap(
                token_mint=token_mint,
                amount=sniper_config["buy_amount"],
                slippage=sniper_config["max_slippage"],
                wallet_address=sniper_config["wallet_address"],
                private_key=sniper_config["private_key"],
                is_sell=False
            )
            
            if tx_result["success"]:
                # Record successful snipe
                await self._record_snipe(
                    sniper_id=sniper_id,
                    token_mint=token_mint,
                    buy_amount=sniper_config["buy_amount"],
                    buy_price=token_info["price"],
                    buy_signature=tx_result["signature"],
                    success=True
                )
                
                # Update sniper stats
                self.active_snipers[sniper_id]["successful_snipes"] += 1
                
                logger.info(f"✅ Snipe successful: {tx_result['signature']}")
                
                # Start monitoring for sell if auto-sell is enabled
                if sniper_config["auto_sell"]:
                    asyncio.create_task(self._monitor_sell_opportunity(
                        sniper_id, token_mint, token_info["price"]
                    ))
            else:
                # Record failed snipe
                await self._record_snipe(
                    sniper_id=sniper_id,
                    token_mint=token_mint,
                    buy_amount=sniper_config["buy_amount"],
                    buy_price=token_info["price"],
                    buy_signature="",
                    success=False
                )
                
                # Update sniper stats
                self.active_snipers[sniper_id]["failed_snipes"] += 1
                
                logger.error(f"❌ Snipe failed: {tx_result['error']}")
                
        except Exception as e:
            logger.error(f"❌ Error executing snipe: {e}")
    
    async def _monitor_sell_opportunity(self, sniper_id: str, token_mint: str, buy_price: float):
        """Monitor for sell opportunity"""
        try:
            sniper_config = self.active_snipers[sniper_id]
            profit_target = buy_price * (1 + sniper_config["profit_target"])
            stop_loss = buy_price * (1 - sniper_config["stop_loss"])
            
            logger.info(f"📈 Monitoring sell opportunity for {token_mint}")
            
            while sniper_config["is_running"]:
                # Get current price
                current_price = await self.solana_manager.get_token_price(token_mint)
                
                if current_price >= profit_target:
                    await self._execute_sell(sniper_id, token_mint, current_price, "profit")
                    break
                elif current_price <= stop_loss:
                    await self._execute_sell(sniper_id, token_mint, current_price, "stop_loss")
                    break
                
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Error monitoring sell opportunity: {e}")
    
    async def _execute_sell(self, sniper_id: str, token_mint: str, sell_price: float, reason: str):
        """Execute sell order"""
        try:
            sniper_config = self.active_snipers[sniper_id]
            
            logger.info(f"💰 Executing sell for {token_mint} at {sell_price} ({reason})")
            
            # Get token balance and sell
            tx_result = await self.solana_manager.execute_swap(
                token_mint=token_mint,
                amount=0,  # Sell all
                slippage=sniper_config["max_slippage"],
                wallet_address=sniper_config["wallet_address"],
                private_key=sniper_config["private_key"],
                is_sell=True
            )
            
            if tx_result["success"]:
                # Calculate profit
                buy_price = await self._get_buy_price(sniper_id, token_mint)
                profit = (sell_price - buy_price) * tx_result["amount"]
                profit_percentage = ((sell_price - buy_price) / buy_price) * 100
                
                # Update sniper stats
                self.active_snipers[sniper_id]["total_profit"] += profit
                
                # Update snipe record
                await self._update_snipe_record(
                    sniper_id, token_mint, sell_price, tx_result["signature"]
                )
                
                logger.info(f"✅ Sell successful: {tx_result['signature']}, Profit: {profit:.4f} SOL ({profit_percentage:.2f}%)")
            else:
                logger.error(f"❌ Sell failed: {tx_result['error']}")
            
        except Exception as e:
            logger.error(f"❌ Error executing sell: {e}")
    
    # Database operations
    async def _store_sniper_config(self, config: Dict):
        """Store sniper configuration in database"""
        try:
            await self.db_manager.execute(
                """
                INSERT INTO snipers (
                    sniper_id, wallet_address, target_tokens, buy_amount,
                    max_slippage, profit_target, stop_loss, auto_sell,
                    compute_unit_limit, cluster, rpc_url, start_time, is_running
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                (
                    config["sniper_id"], config["wallet_address"], config["target_tokens"],
                    config["buy_amount"], config["max_slippage"], config["profit_target"],
                    config["stop_loss"], config["auto_sell"], config["compute_unit_limit"],
                    config["cluster"], config["rpc_url"], config["start_time"], config["is_running"]
                )
            )
        except Exception as e:
            logger.error(f"❌ Error storing sniper config: {e}")
            raise
    
    async def _record_snipe(self, sniper_id: str, token_mint: str, buy_amount: float,
                           buy_price: float, buy_signature: str, success: bool):
        """Record snipe in database"""
        try:
            await self.db_manager.execute(
                """
                INSERT INTO snipe_records (
                    sniper_id, token_mint, buy_amount, buy_price,
                    buy_signature, buy_time, success
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                (
                    sniper_id, token_mint, buy_amount, buy_price,
                    buy_signature, datetime.now().timestamp(), success
                )
            )
        except Exception as e:
            logger.error(f"❌ Error recording snipe: {e}")
            raise
    
    async def _update_snipe_record(self, sniper_id: str, token_mint: str, sell_price: float, sell_signature: str):
        """Update snipe record with sell information"""
        try:
            await self.db_manager.execute(
                """
                UPDATE snipe_records SET
                    sell_price = $1, sell_signature = $2, sell_time = $3
                WHERE sniper_id = $4 AND token_mint = $5 AND sell_price IS NULL
                """,
                (sell_price, sell_signature, datetime.now().timestamp(), sniper_id, token_mint)
            )
        except Exception as e:
            logger.error(f"❌ Error updating snipe record: {e}")
            raise
    
    async def _get_sniper_history(self, sniper_id: str) -> List[Dict]:
        """Get sniper history from database"""
        try:
            results = await self.db_manager.fetch_all(
                "SELECT * FROM snipe_records WHERE sniper_id = $1 ORDER BY buy_time DESC",
                (sniper_id,)
            )
            return results
        except Exception as e:
            logger.error(f"❌ Error getting sniper history: {e}")
            return []
    
    async def _get_buy_price(self, sniper_id: str, token_mint: str) -> float:
        """Get buy price for token"""
        try:
            result = await self.db_manager.fetch_one(
                "SELECT buy_price FROM snipe_records WHERE sniper_id = $1 AND token_mint = $2 ORDER BY buy_time DESC LIMIT 1",
                (sniper_id, token_mint)
            )
            return result["buy_price"] if result else 0.0
        except Exception as e:
            logger.error(f"❌ Error getting buy price: {e}")
            return 0.0
    
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
    
    def _validate_token_mint(self, token_mint: str) -> bool:
        """Validate Solana token mint address"""
        try:
            # Basic validation for Solana mint address format
            if len(token_mint) != 44:  # Base58 encoded Solana address length
                return False
            
            # Check if it's a valid base58 string
            import base58
            base58.b58decode(token_mint)
            return True
            
        except Exception:
            return False 