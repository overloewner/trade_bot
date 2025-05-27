"""Database models and operations."""

import asyncio
import asyncpg
from typing import List, Dict, Optional, Any
from datetime import datetime
from config.settings import Config
import structlog

logger = structlog.get_logger()


class DatabaseManager:
    """Database connection and operations manager."""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
    
    async def init_db(self) -> None:
        """Initialize database connection pool."""
        try:
            self.pool = await asyncpg.create_pool(
                Config.DATABASE_URL,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            await self.create_tables()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    async def close(self) -> None:
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
    
    async def create_tables(self) -> None:
        """Create necessary database tables."""
        async with self.pool.acquire() as conn:
            # Users table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    is_active BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Presets table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS presets (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    name VARCHAR(100) NOT NULL,
                    pairs TEXT[] NOT NULL,
                    intervals TEXT[] NOT NULL,
                    percent_change DECIMAL(5,2) NOT NULL,
                    is_active BOOLEAN DEFAULT false,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Gas alerts table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gas_alerts (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    threshold_gwei DECIMAL(10,2) NOT NULL,
                    is_active BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Create indexes for performance
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_presets_user_active ON presets(user_id, is_active)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_gas_alerts_active ON gas_alerts(is_active)")
    
    async def create_user(self, user_id: int, username: str = None) -> bool:
        """Create or update user."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO users (user_id, username) 
                    VALUES ($1, $2) 
                    ON CONFLICT (user_id) 
                    DO UPDATE SET username = $2, updated_at = NOW()
                    """,
                    user_id, username
                )
                return True
            except Exception as e:
                logger.error(f"Failed to create user {user_id}: {e}")
                return False
    
    async def create_preset(self, user_id: int, name: str, pairs: List[str], 
                          intervals: List[str], percent_change: float) -> Optional[int]:
        """Create new preset."""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.fetchrow(
                    """
                    INSERT INTO presets (user_id, name, pairs, intervals, percent_change)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                    """,
                    user_id, name, pairs, intervals, percent_change
                )
                return result['id']
            except Exception as e:
                logger.error(f"Failed to create preset for user {user_id}: {e}")
                return None
    
    async def get_user_presets(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all presets for user."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM presets WHERE user_id = $1 ORDER BY created_at DESC",
                user_id
            )
            return [dict(row) for row in rows]
    
    async def get_active_presets(self) -> List[Dict[str, Any]]:
        """Get all active presets."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM presets WHERE is_active = true"
            )
            return [dict(row) for row in rows]
    
    async def update_preset_status(self, preset_id: int, is_active: bool) -> bool:
        """Update preset active status."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE presets SET is_active = $1, updated_at = NOW() WHERE id = $2",
                    is_active, preset_id
                )
                return True
            except Exception as e:
                logger.error(f"Failed to update preset {preset_id}: {e}")
                return False
    
    async def delete_preset(self, preset_id: int, user_id: int) -> bool:
        """Delete preset."""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute(
                    "DELETE FROM presets WHERE id = $1 AND user_id = $2",
                    preset_id, user_id
                )
                return result.split()[-1] == '1'
            except Exception as e:
                logger.error(f"Failed to delete preset {preset_id}: {e}")
                return False
    
    async def set_gas_alert(self, user_id: int, threshold_gwei: float) -> bool:
        """Set gas alert threshold."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO gas_alerts (user_id, threshold_gwei)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id)
                    DO UPDATE SET threshold_gwei = $2, updated_at = NOW()
                    """,
                    user_id, threshold_gwei
                )
                return True
            except Exception as e:
                logger.error(f"Failed to set gas alert for user {user_id}: {e}")
                return False
    
    async def get_gas_alerts(self) -> List[Dict[str, Any]]:
        """Get all active gas alerts."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM gas_alerts WHERE is_active = true"
            )
            return [dict(row) for row in rows]
    
    async def get_user_gas_alert(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user's gas alert."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gas_alerts WHERE user_id = $1",
                user_id
            )
            return dict(row) if row else None
    
    async def toggle_gas_alert(self, user_id: int, is_active: bool) -> bool:
        """Toggle gas alert status."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE gas_alerts SET is_active = $1, updated_at = NOW() WHERE user_id = $2",
                    is_active, user_id
                )
                return True
            except Exception as e:
                logger.error(f"Failed to toggle gas alert for user {user_id}: {e}")
                return False


# Global database manager instance
db_manager = DatabaseManager()