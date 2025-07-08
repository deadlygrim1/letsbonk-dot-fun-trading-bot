"""
Configuration settings for LetsBonkDotFun Solana Trading Bot
"""

import os
from typing import Optional
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    app_name: str = "LetsBonkDotFun Solana Trading Bot"
    app_version: str = "1.0.0"
    debug: bool = Field(default=False, env="DEBUG")
    
    # gRPC Configuration
    grpc_host: str = Field(default="localhost", env="GRPC_HOST")
    grpc_port: int = Field(default=50051, env="GRPC_PORT")
    
    # Database Configuration
    database_url: str = Field(
        default="postgresql://trading_user:trading_password@localhost:5432/trading_bot",
        env="DATABASE_URL"
    )
    
    # Redis Configuration
    redis_url: str = Field(
        default="redis://localhost:6379",
        env="REDIS_URL"
    )
    
    # Solana Configuration
    solana_rpc_url: str = Field(
        default="https://api.mainnet-beta.solana.com",
        env="SOLANA_RPC_URL"
    )
    solana_ws_url: str = Field(
        default="wss://api.mainnet-beta.solana.com",
        env="SOLANA_WS_URL"
    )
    solana_commitment: str = Field(
        default="confirmed",
        env="SOLANA_COMMITMENT"
    )
    solana_cluster: str = Field(
        default="mainnet-beta",
        env="SOLANA_CLUSTER"
    )
    
    # Wallet Configuration
    wallet_private_key: Optional[str] = Field(default=None, env="WALLET_PRIVATE_KEY")
    wallet_address: Optional[str] = Field(default=None, env="WALLET_ADDRESS")
    
    # Trading Configuration
    max_slippage: float = Field(default=0.05, env="MAX_SLIPPAGE")  # 5%
    priority_fee: int = Field(default=5000, env="PRIORITY_FEE")  # lamports
    compute_unit_limit: int = Field(default=200000, env="COMPUTE_UNIT_LIMIT")
    compute_unit_price: int = Field(default=1000, env="COMPUTE_UNIT_PRICE")  # micro-lamports
    
    # Sniper Configuration
    sniper_enabled: bool = Field(default=True, env="SNIPER_ENABLED")
    sniper_profit_target: float = Field(default=0.5, env="SNIPER_PROFIT_TARGET")  # 50%
    sniper_stop_loss: float = Field(default=0.2, env="SNIPER_STOP_LOSS")  # 20%
    sniper_auto_sell: bool = Field(default=True, env="SNIPER_AUTO_SELL")
    
    # Copy Trading Configuration
    copy_trading_enabled: bool = Field(default=True, env="COPY_TRADING_ENABLED")
    copy_trading_allocation: float = Field(default=0.1, env="COPY_TRADING_ALLOCATION")  # 10%
    copy_trading_max_position: float = Field(default=0.05, env="COPY_TRADING_MAX_POSITION")  # 5%
    copy_trading_min_amount: float = Field(default=0.01, env="COPY_TRADING_MIN_AMOUNT")  # 0.01 SOL
    copy_trading_max_trades_per_hour: int = Field(default=10, env="COPY_TRADING_MAX_TRADES_PER_HOUR")
    
    # Risk Management
    max_daily_loss: float = Field(default=0.1, env="MAX_DAILY_LOSS")  # 10%
    max_position_size: float = Field(default=0.05, env="MAX_POSITION_SIZE")  # 5%
    stop_loss_percentage: float = Field(default=0.2, env="STOP_LOSS_PERCENTAGE")  # 20%
    take_profit_percentage: float = Field(default=0.5, env="TAKE_PROFIT_PERCENTAGE")  # 50%
    
    # DEX Configuration
    jupiter_enabled: bool = Field(default=True, env="JUPITER_ENABLED")
    raydium_enabled: bool = Field(default=True, env="RAYDIUM_ENABLED")
    orca_enabled: bool = Field(default=True, env="ORCA_ENABLED")
    serum_enabled: bool = Field(default=True, env="SERUM_ENABLED")
    
    # Jupiter API Configuration
    jupiter_api_url: str = Field(
        default="https://quote-api.jup.ag/v6",
        env="JUPITER_API_URL"
    )
    jupiter_swap_url: str = Field(
        default="https://quote-api.jup.ag/v6/swap",
        env="JUPITER_SWAP_URL"
    )
    
    # Raydium Configuration
    raydium_api_url: str = Field(
        default="https://api.raydium.io/v2",
        env="RAYDIUM_API_URL"
    )
    
    # API Keys
    helius_api_key: Optional[str] = Field(default=None, env="HELIUS_API_KEY")
    quicknode_api_key: Optional[str] = Field(default=None, env="QUICKNODE_API_KEY")
    alchemy_api_key: Optional[str] = Field(default=None, env="ALCHEMY_API_KEY")
    
    # External APIs
    coinmarketcap_api_key: Optional[str] = Field(default=None, env="COINMARKETCAP_API_KEY")
    dex_screener_api_key: Optional[str] = Field(default=None, env="DEX_SCREENER_API_KEY")
    
    # Monitoring
    prometheus_enabled: bool = Field(default=True, env="PROMETHEUS_ENABLED")
    prometheus_port: int = Field(default=9090, env="PROMETHEUS_PORT")
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_file: str = Field(default="logs/trading_bot.log", env="LOG_FILE")
    
    # Security
    jwt_secret: str = Field(default="your-secret-key", env="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    jwt_expiration: int = Field(default=3600, env="JWT_EXPIRATION")  # 1 hour
    
    # Rate Limiting
    rate_limit_requests: int = Field(default=100, env="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=60, env="RATE_LIMIT_WINDOW")  # seconds
    
    # WebSocket Configuration
    websocket_enabled: bool = Field(default=True, env="WEBSOCKET_ENABLED")
    websocket_port: int = Field(default=8080, env="WEBSOCKET_PORT")
    
    # Web Dashboard
    web_dashboard_enabled: bool = Field(default=True, env="WEB_DASHBOARD_ENABLED")
    web_dashboard_port: int = Field(default=3000, env="WEB_DASHBOARD_PORT")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    def get_rpc_url(self) -> str:
        """Get Solana RPC URL"""
        return self.solana_rpc_url
    
    def get_ws_url(self) -> str:
        """Get Solana WebSocket URL"""
        return self.solana_ws_url
    
    def get_commitment(self) -> str:
        """Get Solana commitment level"""
        return self.solana_commitment
    
    def get_cluster(self) -> str:
        """Get Solana cluster"""
        return self.solana_cluster
    
    def validate_settings(self) -> bool:
        """Validate required settings"""
        required_fields = [
            "database_url",
            "redis_url",
            "solana_rpc_url"
        ]
        
        for field in required_fields:
            if not getattr(self, field):
                raise ValueError(f"Required setting {field} is not configured")
        
        return True 