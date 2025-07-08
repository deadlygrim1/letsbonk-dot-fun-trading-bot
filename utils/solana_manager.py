"""
Solana Blockchain Manager - Handle Solana-specific operations
"""

import asyncio
import base58
from typing import Dict, List, Optional, Any
from decimal import Decimal

import aiohttp
from loguru import logger
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solana.transaction import Transaction
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction as SoldersTransaction

from config.settings import Settings


class SolanaManager:
    """Solana blockchain manager"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncClient(settings.get_rpc_url(), commitment=Commitment(settings.get_commitment()))
        self.jupiter_api_url = settings.jupiter_api_url
        self.jupiter_swap_url = settings.jupiter_swap_url
        
    async def initialize(self):
        """Initialize Solana client"""
        try:
            # Test connection
            await self.client.get_health()
            logger.info("✅ Solana client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Solana client: {e}")
            raise
    
    async def close(self):
        """Close Solana client"""
        try:
            await self.client.close()
            logger.info("✅ Solana client closed")
        except Exception as e:
            logger.error(f"❌ Error closing Solana client: {e}")
    
    async def get_balance(self, wallet_address: str) -> Dict[str, Any]:
        """Get SOL balance for wallet"""
        try:
            pubkey = PublicKey(wallet_address)
            response = await self.client.get_balance(pubkey)
            
            if response.value is not None:
                balance_lamports = response.value
                balance_sol = balance_lamports / 1_000_000_000  # Convert lamports to SOL
                
                return {
                    "success": True,
                    "balance": balance_sol,
                    "balance_lamports": balance_lamports,
                    "symbol": "SOL"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to get balance"
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting balance: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_token_balance(self, token_mint: str, wallet_address: str) -> Dict[str, Any]:
        """Get SPL token balance for wallet"""
        try:
            # This would use SPL token program to get balance
            # For now, return placeholder
            return {
                "success": True,
                "balance": 0.0,
                "token_mint": token_mint,
                "wallet_address": wallet_address
            }
        except Exception as e:
            logger.error(f"❌ Error getting token balance: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_token_info(self, token_mint: str) -> Dict[str, Any]:
        """Get token information"""
        try:
            # Get token metadata from Jupiter or other sources
            async with aiohttp.ClientSession() as session:
                url = f"{self.jupiter_api_url}/tokens"
                async with session.get(url) as response:
                    if response.status == 200:
                        tokens = await response.json()
                        
                        # Find token by mint address
                        for token in tokens:
                            if token.get("address") == token_mint:
                                return {
                                    "success": True,
                                    "token_mint": token_mint,
                                    "name": token.get("name", ""),
                                    "symbol": token.get("symbol", ""),
                                    "decimals": token.get("decimals", 0),
                                    "price": token.get("price", 0.0),
                                    "liquidity": token.get("liquidity", 0.0),
                                    "is_verified": token.get("verified", False)
                                }
                        
                        return {
                            "success": False,
                            "error": "Token not found"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"API request failed: {response.status}"
                        }
                        
        except Exception as e:
            logger.error(f"❌ Error getting token info: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_token_price(self, token_mint: str) -> float:
        """Get current token price"""
        try:
            token_info = await self.get_token_info(token_mint)
            if token_info["success"]:
                return token_info["price"]
            return 0.0
        except Exception as e:
            logger.error(f"❌ Error getting token price: {e}")
            return 0.0
    
    async def get_priority_fee(self) -> Dict[str, int]:
        """Get current priority fees"""
        try:
            # Get recent priority fees from recent blocks
            response = await self.client.get_recent_prioritization_fees([PublicKey("11111111111111111111111111111111")])
            
            if response.value:
                fees = [fee.prioritization_fee for fee in response.value]
                if fees:
                    avg_fee = sum(fees) // len(fees)
                    return {
                        "slow_priority_fee": max(1000, avg_fee // 2),
                        "standard_priority_fee": avg_fee,
                        "fast_priority_fee": avg_fee * 2,
                        "instant_priority_fee": avg_fee * 4
                    }
            
            # Default fees if unable to get from network
            return {
                "slow_priority_fee": 1000,
                "standard_priority_fee": 5000,
                "fast_priority_fee": 10000,
                "instant_priority_fee": 20000
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting priority fee: {e}")
            return {
                "slow_priority_fee": 1000,
                "standard_priority_fee": 5000,
                "fast_priority_fee": 10000,
                "instant_priority_fee": 20000
            }
    
    async def execute_swap(self, token_mint: str, amount: float, slippage: float,
                          wallet_address: str, private_key: str, is_sell: bool = False) -> Dict[str, Any]:
        """Execute token swap using Jupiter"""
        try:
            # Create keypair from private key
            keypair = Keypair.from_secret_key(base58.b58decode(private_key))
            
            # Get quote from Jupiter
            quote = await self._get_jupiter_quote(
                token_mint=token_mint,
                amount=amount,
                slippage=slippage,
                is_sell=is_sell
            )
            
            if not quote["success"]:
                return quote
            
            # Execute swap
            swap_result = await self._execute_jupiter_swap(
                quote_data=quote["data"],
                keypair=keypair
            )
            
            return swap_result
            
        except Exception as e:
            logger.error(f"❌ Error executing swap: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _get_jupiter_quote(self, token_mint: str, amount: float, slippage: float, is_sell: bool) -> Dict[str, Any]:
        """Get swap quote from Jupiter"""
        try:
            # SOL mint address
            sol_mint = "So11111111111111111111111111111111111111112"
            
            # Determine input and output tokens
            if is_sell:
                input_mint = token_mint
                output_mint = sol_mint
            else:
                input_mint = sol_mint
                output_mint = token_mint
            
            # Get quote from Jupiter
            async with aiohttp.ClientSession() as session:
                url = f"{self.jupiter_api_url}/quote"
                params = {
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(int(amount * 1_000_000_000)),  # Convert to lamports
                    "slippageBps": int(slippage * 10000)  # Convert to basis points
                }
                
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        quote_data = await response.json()
                        return {
                            "success": True,
                            "data": quote_data
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Failed to get quote: {response.status}"
                        }
                        
        except Exception as e:
            logger.error(f"❌ Error getting Jupiter quote: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _execute_jupiter_swap(self, quote_data: Dict, keypair: Keypair) -> Dict[str, Any]:
        """Execute swap using Jupiter"""
        try:
            # Get swap transaction
            async with aiohttp.ClientSession() as session:
                url = f"{self.jupiter_swap_url}"
                payload = {
                    "quoteResponse": quote_data,
                    "userPublicKey": str(keypair.public_key),
                    "wrapUnwrapSOL": True
                }
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        swap_data = await response.json()
                        
                        # Sign and send transaction
                        tx_result = await self._sign_and_send_transaction(
                            swap_data["swapTransaction"],
                            keypair
                        )
                        
                        return tx_result
                    else:
                        return {
                            "success": False,
                            "error": f"Failed to get swap transaction: {response.status}"
                        }
                        
        except Exception as e:
            logger.error(f"❌ Error executing Jupiter swap: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _sign_and_send_transaction(self, transaction_data: str, keypair: Keypair) -> Dict[str, Any]:
        """Sign and send transaction"""
        try:
            # Decode transaction
            transaction_bytes = base58.b58decode(transaction_data)
            transaction = Transaction.deserialize(transaction_bytes)
            
            # Add compute budget instructions
            compute_unit_limit_ix = set_compute_unit_limit(self.settings.compute_unit_limit)
            compute_unit_price_ix = set_compute_unit_price(self.settings.compute_unit_price)
            
            transaction.instructions.insert(0, compute_unit_limit_ix)
            transaction.instructions.insert(1, compute_unit_price_ix)
            
            # Sign transaction
            transaction.sign(keypair)
            
            # Send transaction
            response = await self.client.send_transaction(transaction)
            
            if response.value:
                signature = response.value
                
                # Wait for confirmation
                await self.client.confirm_transaction(signature)
                
                return {
                    "success": True,
                    "signature": signature,
                    "amount": 0.0,  # Would calculate from transaction
                    "executed_price": 0.0,  # Would get from transaction
                    "compute_units_used": 0  # Would get from transaction
                }
            else:
                return {
                    "success": False,
                    "error": "Transaction failed"
                }
                
        except Exception as e:
            logger.error(f"❌ Error signing and sending transaction: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_token_balances(self, wallet_address: str) -> List[Dict[str, Any]]:
        """Get all token balances for wallet"""
        try:
            # This would use SPL token program to get all token accounts
            # For now, return empty list
            return []
        except Exception as e:
            logger.error(f"❌ Error getting token balances: {e}")
            return []
    
    async def get_native_balance(self, wallet_address: str, cluster: int) -> Dict[str, Any]:
        """Get native SOL balance"""
        try:
            balance_result = await self.get_balance(wallet_address)
            
            if balance_result["success"]:
                return {
                    "balance": balance_result["balance"],
                    "symbol": "SOL"
                }
            else:
                return {
                    "balance": 0.0,
                    "symbol": "SOL"
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting native balance: {e}")
            return {
                "balance": 0.0,
                "symbol": "SOL"
            }
    
    async def build_transaction(self, order_type: int, token_mint: str, amount: float,
                               slippage: float, priority_fee: int, compute_unit_limit: int) -> Dict[str, Any]:
        """Build transaction for order"""
        try:
            # This would build the appropriate transaction based on order type
            # For now, return placeholder
            return {
                "success": True,
                "transaction_data": "placeholder"
            }
        except Exception as e:
            logger.error(f"❌ Error building transaction: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_transaction(self, tx_data: Dict, wallet_address: str, cluster: int) -> Dict[str, Any]:
        """Send transaction"""
        try:
            # This would send the transaction
            # For now, return placeholder
            return {
                "success": True,
                "signature": "placeholder_signature",
                "executed_price": 0.0,
                "executed_amount": 0.0,
                "compute_units_used": 0
            }
        except Exception as e:
            logger.error(f"❌ Error sending transaction: {e}")
            return {
                "success": False,
                "error": str(e)
            } 