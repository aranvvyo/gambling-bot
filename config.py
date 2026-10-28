from dataclasses import dataclass
from decimal import Decimal
import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _int(name, default):
    try: return int(os.getenv(name, str(default)).strip() or str(default))
    except ValueError as exc: raise ValueError(f"{name} must be an integer") from exc

def _decimal(name, default):
    try:
        value = Decimal(os.getenv(name, str(default)))
        if not value.is_finite(): raise ValueError
        return value
    except Exception as exc: raise ValueError(f"{name} must be a finite number") from exc

def _ids(name):
    try: return frozenset(int(x.strip()) for x in os.getenv(name, "").split(",") if x.strip())
    except ValueError as exc: raise ValueError(f"{name} must be comma-separated Discord IDs") from exc

@dataclass
class Settings:
    token: str = os.getenv("DISCORD_TOKEN", "")
    # Keep deployment-specific Discord IDs in the host environment.
    # Empty allowlists fail closed until an operator configures their own IDs.
    guild_id: int = _int("DISCORD_GUILD_ID", 0)
    admins: frozenset = _ids("ADMIN_USER_IDS")
    owners: frozenset = _ids("OWNER_USER_IDS")
    admin_channel_id: int = _int("ADMIN_CHANNEL_ID", 0)
    fairness_rotation_seconds: int = _int("FAIRNESS_ROTATION_SECONDS", 1800)
    withdrawals_enabled: bool = os.getenv("WITHDRAWALS_ENABLED", "false").lower() == "true"
    log_channels: dict = None
    casino_name: str = os.getenv("CASINO_NAME", "Emerald Vault")
    currency_symbol: str = os.getenv("CURRENCY_SYMBOL", "VC")
    min_bet: int = _int("MIN_BET", 1)
    daily_reward: int = _int("DAILY_REWARD", 100)
    max_bet: int = _int("MAX_BET", 0)  # zero means no per-bet cap
    max_payout: int = _int("MAX_PAYOUT", 1_000_000)
    daily_bet_limit: int = _int("DAILY_BET_LIMIT", 50000)
    house_edge: Decimal = _decimal("HOUSE_EDGE", "0.01")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///casino.db")
    apirone_account: str = os.getenv("APIRONE_ACCOUNT_ID", "")
    apirone_key: str = os.getenv("APIRONE_TRANSFER_KEY", "")
    deposits_enabled: bool = os.getenv("DEPOSITS_ENABLED", "false").strip().lower() == "true"
    deposits_live_verified: bool = os.getenv("DEPOSITS_LIVE_VERIFIED", "false").strip().lower() == "true"
    invoice_lifetime: int = _int("APIRONE_INVOICE_LIFETIME", 3600)
    poll_interval: int = _int("APIRONE_POLL_INTERVAL", 45)
    brand_color: int = int(os.getenv("BRAND_COLOR", "0x1D9A6C"), 0)
    image_url: str = os.getenv("CASINO_BANNER_URL", "")
    game_art_urls: dict = None
    min_deposit: Decimal = _decimal("MIN_DEPOSIT", "0.00001")
    max_deposit: Decimal = _decimal("MAX_DEPOSIT", "10000")
    max_deposit_credit: int = _int("MAX_DEPOSIT_CREDIT", 1000000)
    # Explicit VC per whole coin conversion rates; zero disables auto-credit for that network.
    rate_ltc: Decimal = _decimal("VC_PER_LTC", "0")
    rate_bnb: Decimal = _decimal("VC_PER_USDT_BEP20", "0")
    rate_eth: Decimal = _decimal("VC_PER_USDT_ERC20", "0")
    rate_timestamp_ltc: int = _int("VC_RATE_UPDATED_AT_LTC", 0)
    rate_timestamp_bnb: int = _int("VC_RATE_UPDATED_AT_USDT_BEP20", 0)
    rate_timestamp_eth: int = _int("VC_RATE_UPDATED_AT_USDT_ERC20", 0)
    rate_source_ltc: str = os.getenv("VC_RATE_SOURCE_LTC", "")
    rate_source_bnb: str = os.getenv("VC_RATE_SOURCE_USDT_BEP20", "")
    rate_source_eth: str = os.getenv("VC_RATE_SOURCE_USDT_ERC20", "")
    rate_max_age_seconds: int = _int("VC_RATE_MAX_AGE_SECONDS", 3600)
    maintenance: bool = os.getenv("MAINTENANCE_MODE", "false").lower() == "true"
    def __post_init__(self):
        log_defaults={"general":0,"withdrawal":0,"wins":0,"loss":0,"deposit":0,"bet":0,"admin":0,"security":0,"error":0,"fairness":0}
        object.__setattr__(self,"log_channels",{key:_int(env,log_defaults[key]) for key,env in {"general":"GENERAL_LOG_CHANNEL_ID","withdrawal":"WITHDRAWAL_LOG_CHANNEL_ID","wins":"WINS_LOG_CHANNEL_ID","loss":"LOSS_LOG_CHANNEL_ID","deposit":"DEPOSIT_LOG_CHANNEL_ID","bet":"BET_LOG_CHANNEL_ID","admin":"ADMIN_LOG_CHANNEL_ID","security":"SECURITY_LOG_CHANNEL_ID","error":"ERROR_LOG_CHANNEL_ID","fairness":"FAIRNESS_LOG_CHANNEL_ID"}.items()})
        object.__setattr__(self,"game_art_urls",{
            "mines":os.getenv("MINES_IMAGE_URL",""),
            "blackjack":os.getenv("BLACKJACK_IMAGE_URL",""),
            "dragon":os.getenv("DRAGON_TOWER_IMAGE_URL",""),
            "crash":os.getenv("CRASH_IMAGE_URL",""),
            "limbo":os.getenv("LIMBO_IMAGE_URL",""),
            "limo":os.getenv("LIMO_IMAGE_URL",""),
            "dice":os.getenv("DICE_IMAGE_URL",""),
            "chicken-road":os.getenv("CHICKEN_ROAD_IMAGE_URL",""),
            "pump":os.getenv("PUMP_IMAGE_URL","")})
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    def validate(self):
        self.token=self.token.strip()
        if not self.token: raise ValueError("DISCORD_TOKEN is required")
        if any(x <= 0 for x in (*self.admins, *self.owners)): raise ValueError("configured Discord user IDs must be positive")
        if any(x < 0 for x in (self.guild_id,self.admin_channel_id,*self.log_channels.values())): raise ValueError("Discord channel and guild IDs cannot be negative")
        if self.withdrawals_enabled: raise ValueError("WITHDRAWALS_ENABLED must remain false until a verified payout provider is implemented")
        self.apirone_account=self.apirone_account.strip()
        self.apirone_key=self.apirone_key.strip()
        if bool(self.apirone_account) != bool(self.apirone_key): raise ValueError("APIRONE_ACCOUNT_ID and APIRONE_TRANSFER_KEY must be configured together")
        if self.poll_interval < 15: raise ValueError("APIRONE_POLL_INTERVAL must be at least 15 seconds")
        if self.fairness_rotation_seconds < 60: raise ValueError("FAIRNESS_ROTATION_SECONDS must be at least 60")
        if self.daily_reward < 0 or self.daily_reward > self.max_payout: raise ValueError("DAILY_REWARD must be between 0 and MAX_PAYOUT")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,9}", self.currency_symbol): raise ValueError("CURRENCY_SYMBOL must use 1–10 safe letters, numbers, underscores, or hyphens")
        if self.min_bet < 1 or (self.max_bet != 0 and self.max_bet < self.min_bet): raise ValueError("MIN_BET/MAX_BET configuration is invalid; MAX_BET=0 means no per-bet cap")
        if self.max_bet and self.max_payout < self.max_bet: raise ValueError("MAX_PAYOUT must be at least MAX_BET")
        if self.daily_bet_limit < self.min_bet: raise ValueError("DAILY_BET_LIMIT must be at least MIN_BET")
        if not Decimal(0) <= self.house_edge <= Decimal("0.25"): raise ValueError("HOUSE_EDGE must be in [0,0.25]")

        if not self.database_url.startswith("sqlite:///"): raise ValueError("This build supports SQLite; DATABASE_URL must begin sqlite:///")
        if not self.database_url.removeprefix("sqlite:///").strip(): raise ValueError("DATABASE_URL must include a SQLite database path")
        if self.max_deposit < self.min_deposit or self.min_deposit <= 0: raise ValueError("MIN_DEPOSIT/MAX_DEPOSIT are invalid")
        if min(self.rate_ltc,self.rate_bnb,self.rate_eth) < 0: raise ValueError("VC conversion rates cannot be negative")
        if self.rate_max_age_seconds < 60: raise ValueError("VC_RATE_MAX_AGE_SECONDS must be at least 60")
        if self.max_deposit_credit<1: raise ValueError("MAX_DEPOSIT_CREDIT must be positive")
        if not 0 <= self.brand_color <= 0xFFFFFF: raise ValueError("BRAND_COLOR must be a 24-bit hex color")
        if self.invoice_lifetime < 60: raise ValueError("APIRONE_INVOICE_LIFETIME must be at least 60")
        return self

settings = Settings()
