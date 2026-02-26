import aiosqlite
import asyncio
import logging
from datetime import datetime, timedelta
import json
import os

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db_path = "bot_database.db"
        self.conn = None
        self.lock = asyncio.Lock()
        self.initialized = False

    async def initialize(self):
        if self.initialized:
            return

        try:
            self.conn = await aiosqlite.connect(self.db_path)

            # Optimize SQLite
            await self.conn.execute("PRAGMA foreign_keys = ON;")
            await self.conn.execute("PRAGMA journal_mode = WAL;")
            await self.conn.execute("PRAGMA busy_timeout = 5000;")
            await self.conn.execute("PRAGMA synchronous = NORMAL;")
            await self.conn.execute("PRAGMA cache_size = -2000;")
            await self.conn.execute("PRAGMA temp_store = MEMORY;")
            self.conn.row_factory = aiosqlite.Row

            # Create tables
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    joined_at TEXT NOT NULL,
                    is_banned INTEGER DEFAULT 0
                )
            ''')

            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS works (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    link TEXT NOT NULL,
                    added_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            ''')

            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    work TEXT NOT NULL,
                    chapter INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    assigned_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    submitted_at TEXT,
                    approved_at TEXT,
                    rejected_at TEXT,
                    approved_by INTEGER,
                    rejected_by INTEGER,
                    reject_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
                    FOREIGN KEY (work) REFERENCES works (name) ON DELETE RESTRICT
                )
            ''')

            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    work TEXT NOT NULL,
                    chapter INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    approved_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
                    FOREIGN KEY (work) REFERENCES works (name) ON DELETE RESTRICT,
                    UNIQUE(user_id, work, chapter)
                )
            ''')

            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    target_id TEXT,
                    details TEXT,
                    timestamp TEXT NOT NULL,
                    type TEXT DEFAULT 'normal'
                )
            ''')

            # ✅ جدول الأدمن الجديد
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id TEXT PRIMARY KEY,
                    added_by INTEGER NOT NULL,
                    added_at TEXT NOT NULL
                )
            ''')

            # Indexes
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tasks_user_status 
                ON tasks(user_id, status)
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tasks_work_chapter 
                ON tasks(work, chapter)
            ''')
            await self.conn.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_unique_pending 
                ON tasks(user_id, work, chapter) 
                WHERE status IN ('pending', 'submitted')
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_chapters_user_date 
                ON chapters(user_id, created_at DESC)
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_logs_timestamp 
                ON logs(timestamp)
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_logs_type 
                ON logs(type)
            ''')

            await self.conn.commit()
            self.initialized = True
            logger.info("✅ SQLite database connected and optimized with single connection")

        except Exception as e:
            logger.error(f"❌ Database error: {e}")
            if self.conn:
                await self.conn.close()
            raise

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None
            self.initialized = False

    def _now(self):
        return datetime.utcnow().isoformat()

    # ========== User Operations ==========
    async def get_or_create_user(self, user_id: str, username: str, display_name: str = None):
        async with self.lock:
            cursor = await self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            user = await cursor.fetchone()
            if not user:
                await self.conn.execute(
                    '''INSERT INTO users (user_id, username, display_name, joined_at, is_banned)
                       VALUES (?, ?, ?, ?, ?)''',
                    (user_id, username, display_name or username, self._now(), 0)
                )
                await self.conn.commit()
                return {
                    "user_id": user_id,
                    "username": username,
                    "display_name": display_name or username,
                    "joined_at": self._now(),
                    "is_banned": False
                }
            if display_name and user["display_name"] != display_name:
                await self.conn.execute(
                    "UPDATE users SET display_name = ? WHERE user_id = ?",
                    (display_name, user_id)
                )
                await self.conn.commit()
            return dict(user)

    # ✅ دوال إدارة الأدمن
    async def add_admin(self, user_id: str, added_by: int) -> bool:
        async with self.lock:
            await self.conn.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                (user_id, added_by, self._now())
            )
            await self.conn.commit()
            return self.conn.total_changes > 0

    async def remove_admin(self, user_id: str) -> bool:
        async with self.lock:
            await self.conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            await self.conn.commit()
            return self.conn.total_changes > 0

    async def is_admin(self, user_id: str) -> bool:
        cursor = await self.conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return await cursor.fetchone() is not None

    async def get_admins(self):
        cursor = await self.conn.execute("SELECT user_id, added_at FROM admins ORDER BY added_at")
        rows = await cursor.fetchall()
        return [{"user_id": row[0], "added_at": row[1]} for row in rows]

    # ========== باقي الدوال (عمل، مهام، إحصائيات، تسجيل) ==========
    # (تأكد من بقاء باقي الدوال كما هي من ملفك السابق، لم يتم تغييرها)
    # سأضيف هنا دوال العمل والمهام والإحصائيات والـ logging للاختصار، لكن في ملفك الفعلي يجب أن تبقى كل الدوال الموجودة سابقاً.
    # أنصحك بإضافة دوال add_admin وما فوق فقط، والاحتفاظ بباقي دوالك القديمة دون تغيير.
    # إذا أردت، يمكنك نسخ دوالك القديمة وإضافتها هنا.
