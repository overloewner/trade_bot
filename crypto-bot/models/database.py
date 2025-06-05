from sqlalchemy import create_engine, Column, BigInteger, String, Boolean, DECIMAL, ARRAY, ForeignKey, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
from sqlalchemy.pool import QueuePool
from typing import List, Optional
import asyncio
from asyncpg import create_pool
import asyncpg

from config.settings import config

Base = declarative_base()


class User(Base):
    """Модель пользователя"""
    __tablename__ = 'users'
    
    user_id = Column(BigInteger, primary_key=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    # Relationships
    presets = relationship("Preset", back_populates="user", cascade="all, delete-orphan")
    gas_alert = relationship("GasAlert", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Preset(Base):
    """Модель пресета для свечных алертов"""
    __tablename__ = 'presets'
    
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'))
    name = Column(String(100), nullable=False)
    pairs = Column(ARRAY(String), nullable=False)
    intervals = Column(ARRAY(String), nullable=False)
    percent_change = Column(DECIMAL(5, 2), nullable=False)
    is_active = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="presets")


class GasAlert(Base):
    """Модель газовых пресетов"""
    __tablename__ = 'gas_alerts'
    
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), primary_key=True)
    threshold_gwei = Column(DECIMAL(10, 2), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="gas_alert")


class DatabaseManager:
    """Асинхронный менеджер базы данных"""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        
    async def init(self):
        """Инициализация пула соединений"""
        self.pool = await create_pool(
            config.DATABASE_URL,
            min_size=10,
            max_size=config.DB_POOL_SIZE,
            max_queries=config.DB_MAX_QUERIES,
max_inactive_connection_lifetime=config.DB_CONNECTION_TIMEOUT,
        )
        await self._create_tables()
    
    async def close(self):
        """Закрытие пула соединений"""
        if self.pool:
            await self.pool.close()
    
    async def _create_tables(self):
        """Создание таблиц если их нет"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    is_active BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS presets (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    name VARCHAR(100) NOT NULL,
                    pairs TEXT[] NOT NULL,
                    intervals TEXT[] NOT NULL,
                    percent_change DECIMAL(5,2) NOT NULL,
                    is_active BOOLEAN DEFAULT false,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS gas_alerts (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    threshold_gwei DECIMAL(10,2) NOT NULL
                )
            ''')
            
            # Создаем индексы для оптимизации
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_presets_user_active 
                ON presets(user_id, is_active)
            ''')
    
    # User operations
    async def create_user(self, user_id: int) -> bool:
        """Создание нового пользователя"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    'INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING',
                    user_id
                )
                return True
            except Exception as e:
                print(f"Error creating user: {e}")
                return False
    
    async def get_user(self, user_id: int) -> Optional[dict]:
        """Получение пользователя"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM users WHERE user_id = $1',
                user_id
            )
            return dict(row) if row else None
    
    # Preset operations
    async def create_preset(self, user_id: int, name: str, pairs: List[str], 
                          intervals: List[str], percent_change: float) -> Optional[int]:
        """Создание нового пресета"""
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    '''INSERT INTO presets (user_id, name, pairs, intervals, percent_change)
                       VALUES ($1, $2, $3, $4, $5) RETURNING id''',
                    user_id, name, pairs, intervals, percent_change
                )
                return row['id']
            except Exception as e:
                print(f"Error creating preset: {e}")
                return None
    
    async def get_user_presets(self, user_id: int) -> List[dict]:
        """Получение всех пресетов пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT * FROM presets WHERE user_id = $1 ORDER BY created_at DESC',
                user_id
            )
            return [dict(row) for row in rows]
    
    async def get_preset(self, preset_id: int) -> Optional[dict]:
        """Получение пресета по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM presets WHERE id = $1',
                preset_id
            )
            return dict(row) if row else None
    
    async def update_preset_status(self, preset_id: int, is_active: bool) -> bool:
        """Обновление статуса пресета"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    'UPDATE presets SET is_active = $1 WHERE id = $2',
                    is_active, preset_id
                )
                return True
            except Exception as e:
                print(f"Error updating preset status: {e}")
                return False
    
    async def delete_preset(self, preset_id: int) -> bool:
        """Удаление пресета"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    'DELETE FROM presets WHERE id = $1',
                    preset_id
                )
                return True
            except Exception as e:
                print(f"Error deleting preset: {e}")
                return False
    
    async def get_all_active_presets(self) -> List[dict]:
        """Получение всех активных пресетов для загрузки в кеш"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                '''SELECT p.*, u.user_id 
                   FROM presets p 
                   JOIN users u ON p.user_id = u.user_id 
                   WHERE p.is_active = true AND u.is_active = true'''
            )
            return [dict(row) for row in rows]
    
    # Gas alert operations
    async def set_gas_alert(self, user_id: int, threshold_gwei: float) -> bool:
        """Установка газового пресета (создание или замена)"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    '''INSERT INTO gas_alerts (user_id, threshold_gwei) 
                       VALUES ($1, $2) 
                       ON CONFLICT (user_id) DO UPDATE 
                       SET threshold_gwei = $2''',
                    user_id, threshold_gwei
                )
                return True
            except Exception as e:
                print(f"Error setting gas alert: {e}")
                return False
    
    async def get_gas_alert(self, user_id: int) -> Optional[dict]:
        """Получение газового пресета пользователя"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM gas_alerts WHERE user_id = $1',
                user_id
            )
            return dict(row) if row else None
    
    async def delete_gas_alert(self, user_id: int) -> bool:
        """ПОЛНОЕ удаление газового пресета"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    'DELETE FROM gas_alerts WHERE user_id = $1',
                    user_id
                )
                return True
            except Exception as e:
                print(f"Error deleting gas alert: {e}")
                return False
    
    async def get_all_gas_alerts(self) -> List[dict]:
        """Получение ВСЕХ газовых пресетов (все по определению активны)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                '''SELECT g.*, u.user_id 
                   FROM gas_alerts g 
                   JOIN users u ON g.user_id = u.user_id 
                   WHERE u.is_active = true'''
            )
            return [dict(row) for row in rows]


# Singleton instance
db_manager = DatabaseManager()