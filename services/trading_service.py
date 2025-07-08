"""
Trading Service - Core Solana trading functionality
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
from utils.risk_manager import RiskManager


class TradingService(trading_pb2_grpc.TradingServiceServicer):
    """Trading service implementation"""
    
    def __init__(self, db_manager: DatabaseManager, redis_client: RedisClient):
        self.db_manager = db_manager
        self.redis_client = redis_client
        self.solana_manager = None  # Will be initialized with settings
        self.risk_manager = RiskManager()
        self.running = False
        self.orders: Dict[str, trading_pb2.Order] = {}
        
    async def start(self):
        """Start the trading service"""
        self.running = True
        logger.info("✅ Trading service started")
        
    async def stop(self):
        """Stop the trading service"""
        self.running = False
        logger.info("✅ Trading service stopped")
    
    async def PlaceOrder(self, request: trading_pb2.Order, context) -> trading_pb2.OrderResponse:
        """Place a new trading order"""
        try:
            logger.info(f"📝 Placing order: {request.order_type} {request.amount} for {request.token_mint}")
            
            # Generate order ID
            order_id = str(uuid.uuid4())
            request.order_id = order_id
            request.timestamp = int(datetime.now().timestamp())
            request.status = trading_pb2.OrderStatus.PENDING
            
            # Validate order
            validation_result = await self._validate_order(request)
            if not validation_result["valid"]:
                return trading_pb2.OrderResponse(
                    success=False,
                    message=validation_result["message"]
                )
            
            # Check risk limits
            risk_check = await self.risk_manager.check_order_risk(request)
            if not risk_check["allowed"]:
                return trading_pb2.OrderResponse(
                    success=False,
                    message=f"Risk limit exceeded: {risk_check['reason']}"
                )
            
            # Store order in database
            await self._store_order(request)
            
            # Execute order
            execution_result = await self._execute_order(request)
            
            if execution_result["success"]:
                # Update order status
                request.status = trading_pb2.OrderStatus.EXECUTED
                request.signature = execution_result["signature"]
                request.executed_price = execution_result["executed_price"]
                request.executed_amount = execution_result["executed_amount"]
                
                await self._update_order(request)
                
                logger.info(f"✅ Order executed successfully: {order_id}")
                
                return trading_pb2.OrderResponse(
                    success=True,
                    message="Order executed successfully",
                    order_id=order_id,
                    signature=execution_result["signature"],
                    compute_units_used=execution_result["compute_units_used"],
                    total_cost=execution_result["total_cost"]
                )
            else:
                # Update order status
                request.status = trading_pb2.OrderStatus.FAILED
                await self._update_order(request)
                
                logger.error(f"❌ Order execution failed: {execution_result['error']}")
                
                return trading_pb2.OrderResponse(
                    success=False,
                    message=f"Order execution failed: {execution_result['error']}"
                )
                
        except Exception as e:
            logger.error(f"❌ Error placing order: {e}")
            return trading_pb2.OrderResponse(
                success=False,
                message=f"Internal error: {str(e)}"
            )
    
    async def GetOrder(self, request: trading_pb2.OrderRequest, context) -> trading_pb2.Order:
        """Get order details"""
        try:
            order = await self._get_order(request.order_id)
            if order:
                return order
            else:
                context.abort(grpc.StatusCode.NOT_FOUND, "Order not found")
        except Exception as e:
            logger.error(f"❌ Error getting order: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def CancelOrder(self, request: trading_pb2.OrderRequest, context) -> trading_pb2.OrderResponse:
        """Cancel an order"""
        try:
            order = await self._get_order(request.order_id)
            if not order:
                return trading_pb2.OrderResponse(
                    success=False,
                    message="Order not found"
                )
            
            if order.status != trading_pb2.OrderStatus.PENDING:
                return trading_pb2.OrderResponse(
                    success=False,
                    message="Order cannot be cancelled"
                )
            
            # Cancel order on Solana
            cancellation_result = await self._cancel_order_on_solana(order)
            
            if cancellation_result["success"]:
                order.status = trading_pb2.OrderStatus.CANCELLED
                await self._update_order(order)
                
                logger.info(f"✅ Order cancelled: {request.order_id}")
                
                return trading_pb2.OrderResponse(
                    success=True,
                    message="Order cancelled successfully"
                )
            else:
                return trading_pb2.OrderResponse(
                    success=False,
                    message=f"Failed to cancel order: {cancellation_result['error']}"
                )
                
        except Exception as e:
            logger.error(f"❌ Error cancelling order: {e}")
            return trading_pb2.OrderResponse(
                success=False,
                message=f"Internal error: {str(e)}"
            )
    
    async def GetOrders(self, request: trading_pb2.OrdersRequest, context) -> trading_pb2.OrdersResponse:
        """Get list of orders"""
        try:
            orders = await self._get_orders(
                wallet_address=request.wallet_address,
                status=request.status,
                start_time=request.start_time,
                end_time=request.end_time,
                limit=request.limit,
                offset=request.offset
            )
            
            return trading_pb2.OrdersResponse(
                orders=orders,
                total_count=len(orders)
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting orders: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def GetPortfolio(self, request: trading_pb2.PortfolioRequest, context) -> trading_pb2.Portfolio:
        """Get portfolio information"""
        try:
            portfolio = await self._get_portfolio(request.wallet_address)
            return portfolio
            
        except Exception as e:
            logger.error(f"❌ Error getting portfolio: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def GetBalance(self, request: trading_pb2.BalanceRequest, context) -> trading_pb2.Balance:
        """Get wallet balance"""
        try:
            balance = await self._get_balance(request.wallet_address, request.cluster)
            return balance
            
        except Exception as e:
            logger.error(f"❌ Error getting balance: {e}")
            context.abort(grpc.StatusCode.INTERNAL, f"Internal error: {str(e)}")
    
    async def _validate_order(self, order: trading_pb2.Order) -> Dict:
        """Validate order parameters"""
        try:
            # Check if token mint is valid
            if not self._validate_token_mint(order.token_mint):
                return {"valid": False, "message": "Invalid token mint address"}
            
            # Check if amount is positive
            if order.amount <= 0:
                return {"valid": False, "message": "Amount must be positive"}
            
            # Check if slippage is reasonable
            if order.slippage <= 0 or order.slippage > 0.5:
                return {"valid": False, "message": "Slippage must be between 0 and 50%"}
            
            # Check if wallet address is valid
            if not self._validate_wallet_address(order.wallet_address):
                return {"valid": False, "message": "Invalid wallet address"}
            
            return {"valid": True, "message": "Order is valid"}
            
        except Exception as e:
            return {"valid": False, "message": f"Validation error: {str(e)}"}
    
    async def _execute_order(self, order: trading_pb2.Order) -> Dict:
        """Execute order on Solana"""
        try:
            # Get priority fee
            priority_fees = await self.solana_manager.get_priority_fee()
            
            # Build transaction
            tx_data = await self.solana_manager.build_transaction(
                order_type=order.order_type,
                token_mint=order.token_mint,
                amount=order.amount,
                slippage=order.slippage,
                priority_fee=order.priority_fee,
                compute_unit_limit=order.compute_unit_limit
            )
            
            # Send transaction
            tx_result = await self.solana_manager.send_transaction(
                tx_data=tx_data,
                wallet_address=order.wallet_address,
                cluster=order.cluster
            )
            
            if tx_result["success"]:
                return {
                    "success": True,
                    "signature": tx_result["signature"],
                    "executed_price": tx_result["executed_price"],
                    "executed_amount": tx_result["executed_amount"],
                    "compute_units_used": tx_result["compute_units_used"],
                    "total_cost": tx_result["total_cost"]
                }
            else:
                return {
                    "success": False,
                    "error": tx_result["error"]
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _store_order(self, order: trading_pb2.Order):
        """Store order in database"""
        try:
            # Store in database
            await self.db_manager.execute(
                """
                INSERT INTO orders (
                    order_id, token_mint, amount, order_type, slippage,
                    priority_fee, compute_unit_limit, cluster, wallet_address, status,
                    timestamp, executed_price, executed_amount, signature
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """,
                (
                    order.order_id, order.token_mint, order.amount,
                    order.order_type, order.slippage, order.priority_fee,
                    order.compute_unit_limit, order.cluster, order.wallet_address,
                    order.status, order.timestamp, order.executed_price,
                    order.executed_amount, order.signature
                )
            )
            
            # Store in Redis for fast access
            await self.redis_client.set(
                f"order:{order.order_id}",
                order.SerializeToString(),
                expire=3600  # 1 hour
            )
            
        except Exception as e:
            logger.error(f"❌ Error storing order: {e}")
            raise
    
    async def _update_order(self, order: trading_pb2.Order):
        """Update order in database"""
        try:
            await self.db_manager.execute(
                """
                UPDATE orders SET
                    status = $1, executed_price = $2, executed_amount = $3,
                    signature = $4
                WHERE order_id = $5
                """,
                (
                    order.status, order.executed_price, order.executed_amount,
                    order.signature, order.order_id
                )
            )
            
            # Update in Redis
            await self.redis_client.set(
                f"order:{order.order_id}",
                order.SerializeToString(),
                expire=3600
            )
            
        except Exception as e:
            logger.error(f"❌ Error updating order: {e}")
            raise
    
    async def _get_order(self, order_id: str) -> Optional[trading_pb2.Order]:
        """Get order from database or cache"""
        try:
            # Try Redis first
            cached_order = await self.redis_client.get(f"order:{order_id}")
            if cached_order:
                order = trading_pb2.Order()
                order.ParseFromString(cached_order)
                return order
            
            # Get from database
            result = await self.db_manager.fetch_one(
                "SELECT * FROM orders WHERE order_id = $1",
                (order_id,)
            )
            
            if result:
                order = trading_pb2.Order(
                    order_id=result["order_id"],
                    token_mint=result["token_mint"],
                    amount=result["amount"],
                    order_type=result["order_type"],
                    slippage=result["slippage"],
                    priority_fee=result["priority_fee"],
                    compute_unit_limit=result["compute_unit_limit"],
                    cluster=result["cluster"],
                    wallet_address=result["wallet_address"],
                    status=result["status"],
                    timestamp=result["timestamp"],
                    executed_price=result["executed_price"],
                    executed_amount=result["executed_amount"],
                    signature=result["signature"]
                )
                
                # Cache in Redis
                await self.redis_client.set(
                    f"order:{order_id}",
                    order.SerializeToString(),
                    expire=3600
                )
                
                return order
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error getting order: {e}")
            return None
    
    async def _get_orders(self, wallet_address: str, status: int, start_time: int,
                         end_time: int, limit: int, offset: int) -> List[trading_pb2.Order]:
        """Get orders from database"""
        try:
            query = "SELECT * FROM orders WHERE wallet_address = $1"
            params = [wallet_address]
            
            if status != 0:  # Not PENDING
                query += " AND status = $2"
                params.append(status)
            
            if start_time > 0:
                query += f" AND timestamp >= ${len(params) + 1}"
                params.append(start_time)
            
            if end_time > 0:
                query += f" AND timestamp <= ${len(params) + 1}"
                params.append(end_time)
            
            query += " ORDER BY timestamp DESC"
            
            if limit > 0:
                query += f" LIMIT ${len(params) + 1}"
                params.append(limit)
            
            if offset > 0:
                query += f" OFFSET ${len(params) + 1}"
                params.append(offset)
            
            results = await self.db_manager.fetch_all(query, tuple(params))
            
            orders = []
            for result in results:
                order = trading_pb2.Order(
                    order_id=result["order_id"],
                    token_mint=result["token_mint"],
                    amount=result["amount"],
                    order_type=result["order_type"],
                    slippage=result["slippage"],
                    priority_fee=result["priority_fee"],
                    compute_unit_limit=result["compute_unit_limit"],
                    cluster=result["cluster"],
                    wallet_address=result["wallet_address"],
                    status=result["status"],
                    timestamp=result["timestamp"],
                    executed_price=result["executed_price"],
                    executed_amount=result["executed_amount"],
                    signature=result["signature"]
                )
                orders.append(order)
            
            return orders
            
        except Exception as e:
            logger.error(f"❌ Error getting orders: {e}")
            return []
    
    async def _get_portfolio(self, wallet_address: str) -> trading_pb2.Portfolio:
        """Get portfolio information"""
        try:
            # Get token balances
            balances = await self.solana_manager.get_token_balances(wallet_address)
            
            # Calculate total value
            total_value = sum(balance["value"] for balance in balances)
            
            # Get profit/loss
            profit_info = await self._calculate_profit_loss(wallet_address)
            
            # Build portfolio
            portfolio = trading_pb2.Portfolio(
                wallet_address=wallet_address,
                total_value=total_value,
                total_profit=profit_info["total_profit"],
                total_profit_percentage=profit_info["total_profit_percentage"]
            )
            
            # Add token balances
            for balance in balances:
                token_balance = trading_pb2.TokenBalance(
                    token_mint=balance["token_mint"],
                    symbol=balance["symbol"],
                    balance=balance["balance"],
                    value=balance["value"],
                    price=balance["price"]
                )
                portfolio.tokens.append(token_balance)
            
            return portfolio
            
        except Exception as e:
            logger.error(f"❌ Error getting portfolio: {e}")
            return trading_pb2.Portfolio(wallet_address=wallet_address)
    
    async def _get_balance(self, wallet_address: str, cluster: int) -> trading_pb2.Balance:
        """Get wallet balance"""
        try:
            balance_info = await self.solana_manager.get_native_balance(wallet_address, cluster)
            
            return trading_pb2.Balance(
                wallet_address=wallet_address,
                cluster=cluster,
                balance=balance_info["balance"],
                symbol=balance_info["symbol"]
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting balance: {e}")
            return trading_pb2.Balance(
                wallet_address=wallet_address,
                cluster=cluster,
                balance=0.0,
                symbol=""
            )
    
    async def _cancel_order_on_solana(self, order: trading_pb2.Order) -> Dict:
        """Cancel order on Solana"""
        try:
            # This would implement the actual cancellation logic for Solana
            # For now, return success
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _calculate_profit_loss(self, wallet_address: str) -> Dict:
        """Calculate profit/loss for wallet"""
        try:
            # Get all executed orders
            orders = await self._get_orders(wallet_address, 1, 0, 0, 0, 0)  # EXECUTED status
            
            total_profit = 0.0
            total_invested = 0.0
            
            for order in orders:
                if order.order_type == trading_pb2.OrderType.BUY:
                    total_invested += order.executed_amount * order.executed_price
                elif order.order_type == trading_pb2.OrderType.SELL:
                    total_profit += order.executed_amount * order.executed_price - total_invested
            
            total_profit_percentage = (total_profit / total_invested * 100) if total_invested > 0 else 0
            
            return {
                "total_profit": total_profit,
                "total_profit_percentage": total_profit_percentage
            }
            
        except Exception as e:
            logger.error(f"❌ Error calculating profit/loss: {e}")
            return {"total_profit": 0.0, "total_profit_percentage": 0.0}
    
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