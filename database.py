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

            # Admin table
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

    # ========== Admin Management ==========
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

    # ========== Work Operations ==========
    async def add_work(self, name: str, link: str, added_by: int):
        try:
            async with self.lock:
                await self.conn.execute(
                    '''INSERT INTO works (name, link, added_by, created_at, is_active)
                       VALUES (?, ?, ?, ?, ?)''',
                    (name, link, added_by, self._now(), 1)
                )
                await self.conn.commit()
                await self.log_action("add_work", added_by, details={"name": name, "link": link})
                return True, "✅ تمت الإضافة"
        except Exception:
            return False, "❌ العمل موجود مسبقاً"

    async def get_work(self, name: str):
        cursor = await self.conn.execute(
            "SELECT * FROM works WHERE LOWER(name) = LOWER(?) AND is_active = 1", (name,)
        )
        return await cursor.fetchone()

    async def search_works(self, query: str):
        cursor = await self.conn.execute(
            "SELECT * FROM works WHERE LOWER(name) LIKE LOWER(?) AND is_active = 1 LIMIT 10",
            (f"%{query}%",)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_work(self, name: str, deleted_by: int):
        async with self.lock:
            cursor = await self.conn.execute(
                "UPDATE works SET is_active = 0 WHERE LOWER(name) = LOWER(?)", (name,)
            )
            if cursor.rowcount > 0:
                await self.conn.commit()
                await self.log_action("delete_work", deleted_by, details={"name": name})
                return True
            return False

    # ========== Task Operations ==========
    async def create_task(self, user_id: str, username: str, display_name: str,
                          work: str, chapter: int, price: int, assigned_by: int):
        if price <= 0 or price > 10000:
            return False, "❌ السعر يجب أن يكون بين 1 و 10000"
        if chapter <= 0:
            return False, "❌ رقم الفصل غير صالح"

        work_doc = await self.get_work(work)
        if not work_doc:
            return False, "❌ العمل غير موجود"

        await self.get_or_create_user(user_id, username, display_name)

        async with self.lock:
            try:
                await self.conn.execute(
                    '''INSERT OR IGNORE INTO tasks
                       (user_id, username, display_name, work, chapter, price,
                        status, assigned_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id, username, display_name, work_doc["name"], chapter, price,
                     "pending", assigned_by, self._now())
                )
                await self.conn.commit()
                if self.conn.total_changes > 0:
                    await self.log_action(
                        "create_task", assigned_by, target_id=user_id,
                        details={"work": work_doc["name"], "chapter": chapter, "price": price}
                    )
                    return True, "✅ تم التكليف"
                else:
                    return False, "❌ هذا الفصل مكلف بالفعل"
            except Exception as e:
                logger.error(f"Error creating task: {e}")
                return False, "❌ حدث خطأ"

    async def get_user_tasks(self, user_id: str, status: str = None):
        if status:
            cursor = await self.conn.execute(
                "SELECT * FROM tasks WHERE user_id = ? AND status = ? ORDER BY created_at DESC",
                (user_id, status)
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def submit_task(self, user_id: str, work: str, chapter: int):
        async with self.lock:
            cursor = await self.conn.execute(
                """
                UPDATE tasks
                SET status = ?, submitted_at = ?
                WHERE user_id = ? AND work = ? AND chapter = ? AND status = 'pending'
                """,
                ("submitted", self._now(), user_id, work, chapter)
            )
            await self.conn.commit()
            success = cursor.rowcount > 0
            await self.log_action(
                "submit_task", int(user_id),
                details={"work": work, "chapter": chapter, "success": success}
            )
            return success

    async def approve_task(self, user_id: str, work: str, chapter: int, approved_by: int):
        async with self.lock:
            try:
                await self.conn.execute("BEGIN IMMEDIATE")

                cursor = await self.conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE user_id = ? AND work = ? AND chapter = ?
                      AND status = 'submitted' AND approved_at IS NULL
                    """,
                    (user_id, work, chapter)
                )
                task = await cursor.fetchone()
                if not task:
                    await self.conn.execute("ROLLBACK")
                    return None

                await self.conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'approved', approved_by = ?, approved_at = ?
                    WHERE id = ?
                    """,
                    (approved_by, self._now(), task["id"])
                )

                try:
                    await self.conn.execute(
                        """
                        INSERT INTO chapters
                        (user_id, username, display_name, work, chapter, price, approved_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, task["username"], task["display_name"], work, chapter,
                         task["price"], approved_by, self._now())
                    )
                except Exception:
                    await self.conn.execute("ROLLBACK")
                    return None

                await self.conn.commit()

                await self.log_action(
                    "financial_approve", approved_by, target_id=user_id,
                    details={"work": work, "chapter": chapter, "price": task["price"]},
                    log_type="financial"
                )
                return dict(task)

            except Exception as e:
                await self.conn.execute("ROLLBACK")
                logger.error(f"Error in approve_task: {e}")
                return None

    async def reject_task(self, user_id: str, work: str, chapter: int,
                          rejected_by: int, reason: str):
        async with self.lock:
            cursor = await self.conn.execute(
                """
                UPDATE tasks
                SET status = 'rejected', rejected_by = ?,
                    rejected_at = ?, reject_reason = ?
                WHERE user_id = ? AND work = ? AND chapter = ? AND status = 'submitted'
                """,
                (rejected_by, self._now(), reason, user_id, work, chapter)
            )
            await self.conn.commit()
            if cursor.rowcount > 0:
                await self.log_action(
                    "reject_task", rejected_by, target_id=user_id,
                    details={"work": work, "chapter": chapter, "reason": reason}
                )
                return True
            return False

    # ========== Stats Operations ==========
    async def get_user_stats(self, user_id: str):
        cursor = await self.conn.execute(
            "SELECT COALESCE(SUM(price), 0) as total, COUNT(*) as count FROM chapters WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        total_earned = row["total"]
        chapters_count = row["count"]

        cursor = await self.conn.execute(
            "SELECT * FROM chapters WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        )
        recent = await cursor.fetchall()

        cursor = await self.conn.execute(
            "SELECT COUNT(*) as count FROM tasks WHERE user_id = ? AND status = 'pending'",
            (user_id,)
        )
        pending = (await cursor.fetchone())["count"]

        cursor = await self.conn.execute(
            "SELECT COUNT(*) as count FROM tasks WHERE user_id = ? AND status = 'submitted'",
            (user_id,)
        )
        submitted = (await cursor.fetchone())["count"]

        cursor = await self.conn.execute(
            "SELECT display_name FROM users WHERE user_id = ?", (user_id,)
        )
        user = await cursor.fetchone()

        return {
            "total_earned": total_earned,
            "chapters_count": chapters_count,
            "recent_chapters": [dict(r) for r in recent],
            "pending_tasks": pending,
            "submitted_tasks": submitted,
            "display_name": user["display_name"] if user else None
        }

    async def get_team_stats(self):
        cursor = await self.conn.execute("SELECT COUNT(*) as count FROM chapters")
        total_chapters = (await cursor.fetchone())["count"]

        cursor = await self.conn.execute("SELECT COALESCE(SUM(price), 0) as total FROM chapters")
        total_earnings = (await cursor.fetchone())["total"]

        cursor = await self.conn.execute("SELECT COUNT(*) as count FROM tasks WHERE status = 'pending'")
        pending = (await cursor.fetchone())["count"]

        cursor = await self.conn.execute("SELECT COUNT(*) as count FROM tasks WHERE status = 'submitted'")
        submitted = (await cursor.fetchone())["count"]

        cursor = await self.conn.execute('''
            SELECT user_id, username, display_name, COUNT(*) as count, COALESCE(SUM(price), 0) as total
            FROM chapters GROUP BY user_id ORDER BY count DESC LIMIT 5
        ''')
        top_users = await cursor.fetchall()

        return {
            "total_chapters": total_chapters,
            "total_earnings": total_earnings,
            "pending_tasks": pending,
            "submitted_tasks": submitted,
            "top_users": [dict(u) for u in top_users]
        }

    async def get_weekly_report(self):
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        cursor = await self.conn.execute('''
            SELECT user_id, username, display_name, COUNT(*) as chapters, COALESCE(SUM(price), 0) as earnings
            FROM chapters WHERE created_at >= ? GROUP BY user_id ORDER BY chapters DESC
        ''', (week_ago,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ========== Logging ==========
    async def log_action(self, action: str, user_id: int, target_id: str = None,
                         details: dict = None, log_type: str = "normal"):
        async with self.lock:
            await self.conn.execute(
                '''INSERT INTO logs (action, user_id, target_id, details, timestamp, type)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (action, user_id, target_id, json.dumps(details or {}), self._now(), log_type)
            )
            await self.conn.commit()

    async def delete_all_logs(self, user_id: int):
        async with self.lock:
            try:
                await self.conn.execute("BEGIN IMMEDIATE")

                await self.conn.execute(
                    """
                    INSERT INTO logs (action, user_id, timestamp, type)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("delete_all_logs", user_id, self._now(), "admin")
                )

                await self.conn.execute("DELETE FROM logs WHERE type != 'financial'")
                await self.conn.commit()

            except Exception as e:
                await self.conn.execute("ROLLBACK")
                logger.error(f"Error deleting logs: {e}")

# Create global instance
db = Database()
