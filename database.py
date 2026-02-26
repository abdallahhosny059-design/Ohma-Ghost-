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
        self.data_conn = None
        self.log_conn = None
        self.data_lock = asyncio.Lock()
        self.log_lock = asyncio.Lock()
        self.initialized = False

    async def initialize(self):
        if self.initialized:
            return

        try:
            self.data_conn = await aiosqlite.connect(self.db_path)
            await self.data_conn.execute("PRAGMA foreign_keys = ON;")
            await self.data_conn.execute("PRAGMA journal_mode = WAL;")
            await self.data_conn.execute("PRAGMA busy_timeout = 5000;")
            await self.data_conn.execute("PRAGMA synchronous = NORMAL;")
            await self.data_conn.execute("PRAGMA cache_size = -2000;")
            await self.data_conn.execute("PRAGMA temp_store = MEMORY;")
            self.data_conn.row_factory = aiosqlite.Row

            self.log_conn = await aiosqlite.connect(self.db_path)
            await self.log_conn.execute("PRAGMA journal_mode = WAL;")
            await self.log_conn.execute("PRAGMA busy_timeout = 5000;")
            await self.log_conn.execute("PRAGMA synchronous = NORMAL;")
            self.log_conn.row_factory = aiosqlite.Row

            # إنشاء الجداول
            await self.data_conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    joined_at TEXT NOT NULL,
                    is_banned INTEGER DEFAULT 0
                )
            ''')
            await self.data_conn.execute('''
                CREATE TABLE IF NOT EXISTS works (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    link TEXT NOT NULL,
                    added_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            await self.data_conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    work_id INTEGER NOT NULL,
                    chapter INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    assigned_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    submitted_at TEXT,
                    approved_at TEXT,
                    rejected_at TEXT,
                    approved_by TEXT,
                    rejected_by TEXT,
                    reject_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
                    FOREIGN KEY (work_id) REFERENCES works (id) ON DELETE RESTRICT
                )
            ''')
            await self.data_conn.execute('''
                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    work_id INTEGER NOT NULL,
                    chapter INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
                    FOREIGN KEY (work_id) REFERENCES works (id) ON DELETE RESTRICT,
                    UNIQUE(user_id, work_id, chapter)
                )
            ''')
            await self.data_conn.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    target_id TEXT,
                    details TEXT,
                    timestamp TEXT NOT NULL,
                    type TEXT DEFAULT 'normal'
                )
            ''')
            await self.data_conn.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id TEXT PRIMARY KEY,
                    added_by TEXT NOT NULL,
                    added_at TEXT NOT NULL
                )
            ''')

            # الفهارس
            await self.data_conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status)
            ''')
            await self.data_conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tasks_work_id ON tasks(work_id)
            ''')
            await self.data_conn.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_unique_pending 
                ON tasks(user_id, work_id, chapter) WHERE status IN ('pending', 'submitted')
            ''')
            await self.data_conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_chapters_user_date ON chapters(user_id, created_at DESC)
            ''')
            await self.data_conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_chapters_work_id ON chapters(work_id)
            ''')
            await self.data_conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)
            ''')
            await self.data_conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_logs_type ON logs(type)
            ''')

            await self.data_conn.commit()
            self.initialized = True
            logger.info("✅ Database initialized successfully")

        except Exception as e:
            logger.error(f"❌ Database initialization error: {e}")
            if self.data_conn:
                await self.data_conn.close()
            if self.log_conn:
                await self.log_conn.close()
            raise

    async def close(self):
        if self.data_conn:
            await self.data_conn.close()
        if self.log_conn:
            await self.log_conn.close()
        self.initialized = False

    def _now(self):
        return datetime.utcnow().isoformat()

    # ========== دوال داخلية (بدون قفل) ==========
    async def _get_work_by_id(self, work_id: int):
        cursor = await self.data_conn.execute(
            "SELECT * FROM works WHERE id = ? AND is_active = 1", (work_id,)
        )
        return await cursor.fetchone()

    async def _get_work_id_by_name(self, name: str):
        cursor = await self.data_conn.execute(
            "SELECT id FROM works WHERE LOWER(name) = LOWER(?) AND is_active = 1",
            (name,)
        )
        row = await cursor.fetchone()
        return row["id"] if row else None

    async def _get_user(self, user_id: str):
        cursor = await self.data_conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        return await cursor.fetchone()

    async def _create_user(self, user_id: str, username: str, display_name: str):
        await self.data_conn.execute(
            '''INSERT INTO users (user_id, username, display_name, joined_at, is_banned)
               VALUES (?, ?, ?, ?, ?)''',
            (user_id, username, display_name, self._now(), 0)
        )

    async def _update_user_display_name(self, user_id: str, display_name: str):
        await self.data_conn.execute(
            "UPDATE users SET display_name = ? WHERE user_id = ?",
            (display_name, user_id)
        )

    # ========== التسجيل العام ==========
    async def log_action(self, action: str, user_id: str, target_id: str = None,
                         details: dict = None, log_type: str = "normal", max_retries=3):
        for attempt in range(max_retries):
            try:
                async with self.log_lock:
                    await self.log_conn.execute(
                        '''INSERT INTO logs (action, user_id, target_id, details, timestamp, type)
                           VALUES (?, ?, ?, ?, ?, ?)''',
                        (action, user_id, target_id, json.dumps(details or {}), self._now(), log_type)
                    )
                    await self.log_conn.commit()
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to log action after {max_retries} attempts: {e}")
                else:
                    await asyncio.sleep(0.1 * (2 ** attempt))

    # ========== المستخدمون ==========
    async def get_or_create_user(self, user_id: str, username: str, display_name: str = None):
        async with self.data_lock:
            user = await self._get_user(user_id)
            if not user:
                await self._create_user(user_id, username, display_name or username)
                await self.data_conn.commit()
                return {
                    "user_id": user_id,
                    "username": username,
                    "display_name": display_name or username,
                    "joined_at": self._now(),
                    "is_banned": False
                }
            if display_name and user["display_name"] != display_name:
                await self._update_user_display_name(user_id, display_name)
                await self.data_conn.commit()
            return dict(user)

    async def _get_or_create_user(self, user_id: str, username: str, display_name: str = None):
        # للاستخدام داخل data_lock فقط
        user = await self._get_user(user_id)
        if not user:
            await self._create_user(user_id, username, display_name or username)
            await self.data_conn.commit()
            return {
                "user_id": user_id,
                "username": username,
                "display_name": display_name or username,
                "joined_at": self._now(),
                "is_banned": False
            }
        if display_name and user["display_name"] != display_name:
            await self._update_user_display_name(user_id, display_name)
            await self.data_conn.commit()
        return dict(user)

    # ========== إدارة الأدمن ==========
    async def add_admin(self, user_id: str, added_by: str) -> bool:
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                (user_id, added_by, self._now())
            )
            await self.data_conn.commit()
            success = cursor.rowcount > 0
        if success:
            asyncio.create_task(self.log_action("add_admin", added_by, details={"target_id": user_id}))
        return success

    async def remove_admin(self, user_id: str, removed_by: str) -> bool:
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                "DELETE FROM admins WHERE user_id = ?", (user_id,)
            )
            await self.data_conn.commit()
            success = cursor.rowcount > 0
        if success:
            asyncio.create_task(self.log_action("remove_admin", removed_by, details={"target_id": user_id}))
        return success

    async def is_admin(self, user_id: str) -> bool:
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                "SELECT 1 FROM admins WHERE user_id = ?", (user_id,)
            )
            return await cursor.fetchone() is not None

    async def get_admins(self):
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                "SELECT user_id, added_at FROM admins ORDER BY added_at"
            )
            rows = await cursor.fetchall()
            return [{"user_id": row[0], "added_at": row[1]} for row in rows]

    # ========== الأعمال ==========
    async def add_work(self, name: str, link: str, added_by: str):
        try:
            async with self.data_lock:
                await self.data_conn.execute(
                    '''INSERT INTO works (name, link, added_by, created_at, is_active)
                       VALUES (?, ?, ?, ?, ?)''',
                    (name, link, added_by, self._now(), 1)
                )
                await self.data_conn.commit()
            asyncio.create_task(self.log_action("add_work", added_by, details={"name": name, "link": link}))
            return True, "✅ تمت الإضافة"
        except Exception:
            return False, "❌ العمل موجود مسبقاً"

    async def get_work_by_name(self, name: str):
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                "SELECT * FROM works WHERE LOWER(name) = LOWER(?) AND is_active = 1",
                (name,)
            )
            return await cursor.fetchone()

    async def get_work_by_id(self, work_id: int):
        async with self.data_lock:
            return await self._get_work_by_id(work_id)

    async def search_works(self, query: str):
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                "SELECT * FROM works WHERE LOWER(name) LIKE LOWER(?) AND is_active = 1 LIMIT 10",
                (f"%{query}%",)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_work(self, name: str, deleted_by: str):
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                "UPDATE works SET is_active = 0 WHERE LOWER(name) = LOWER(?) AND is_active = 1",
                (name,)
            )
            await self.data_conn.commit()
            success = cursor.rowcount > 0
        if success:
            asyncio.create_task(self.log_action("delete_work", deleted_by, details={"name": name}))
        return success

    # ========== المهام (مع دوال مساعدة تستقبل اسم العمل) ==========
    async def create_task(self, user_id: str, username: str, display_name: str,
                          work_name: str, chapter: int, price: int, assigned_by: str):
        if price <= 0 or price > 10000:
            return False, "❌ السعر يجب أن يكون بين 1 و 10000"
        if chapter <= 0:
            return False, "❌ رقم الفصل غير صالح"

        async with self.data_lock:
            work_id = await self._get_work_id_by_name(work_name)
            if not work_id:
                return False, "❌ العمل غير موجود"

            await self._get_or_create_user(user_id, username, display_name)

            try:
                cursor = await self.data_conn.execute(
                    '''INSERT OR IGNORE INTO tasks
                       (user_id, username, display_name, work_id, chapter, price,
                        status, assigned_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id, username, display_name, work_id, chapter, price,
                     "pending", assigned_by, self._now())
                )
                await self.data_conn.commit()
                if cursor.rowcount > 0:
                    asyncio.create_task(self.log_action(
                        "create_task", assigned_by, target_id=user_id,
                        details={"work_id": work_id, "chapter": chapter, "price": price}
                    ))
                    return True, "✅ تم التكليف"
                else:
                    return False, "❌ هذا الفصل مكلف بالفعل"
            except Exception as e:
                await self.data_conn.rollback()
                logger.error(f"Error creating task: {e}")
                return False, "❌ حدث خطأ"

    async def get_user_tasks(self, user_id: str, status: str = None):
        async with self.data_lock:
            if status:
                cursor = await self.data_conn.execute('''
                    SELECT t.*, w.name as work_name
                    FROM tasks t
                    JOIN works w ON t.work_id = w.id
                    WHERE t.user_id = ? AND t.status = ?
                    ORDER BY t.created_at DESC
                ''', (user_id, status))
            else:
                cursor = await self.data_conn.execute('''
                    SELECT t.*, w.name as work_name
                    FROM tasks t
                    JOIN works w ON t.work_id = w.id
                    WHERE t.user_id = ?
                    ORDER BY t.created_at DESC
                ''', (user_id,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def submit_task(self, user_id: str, work_id: int, chapter: int):
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                """
                UPDATE tasks
                SET status = ?, submitted_at = ?
                WHERE user_id = ? AND work_id = ? AND chapter = ? AND status = 'pending'
                """,
                ("submitted", self._now(), user_id, work_id, chapter)
            )
            await self.data_conn.commit()
            return cursor.rowcount > 0

    async def submit_task_by_name(self, user_id: str, work_name: str, chapter: int):
        async with self.data_lock:
            work_id = await self._get_work_id_by_name(work_name)
            if not work_id:
                return False
            return await self.submit_task(user_id, work_id, chapter)

    async def approve_task(self, user_id: str, work_id: int, chapter: int, approved_by: str, max_retries=3):
        for attempt in range(max_retries):
            try:
                async with self.data_lock:
                    await self.data_conn.execute("BEGIN IMMEDIATE")

                    cursor = await self.data_conn.execute(
                        """
                        SELECT * FROM tasks
                        WHERE user_id = ? AND work_id = ? AND chapter = ?
                          AND status = 'submitted' AND approved_at IS NULL
                        """,
                        (user_id, work_id, chapter)
                    )
                    task_row = await cursor.fetchone()
                    if not task_row:
                        await self.data_conn.execute("ROLLBACK")
                        logger.warning(f"Approve task failed: no submitted task")
                        return None

                    task = dict(task_row)

                    if task["price"] is None or task["price"] <= 0:
                        logger.error(f"Task {task['id']} invalid price")
                        await self.data_conn.execute("ROLLBACK")
                        return None

                    cursor2 = await self.data_conn.execute(
                        """
                        UPDATE tasks
                        SET status = 'approved', approved_by = ?, approved_at = ?
                        WHERE id = ? AND status = 'submitted'
                        """,
                        (approved_by, self._now(), task["id"])
                    )
                    if cursor2.rowcount == 0:
                        await self.data_conn.execute("ROLLBACK")
                        logger.warning("Approve task race: status changed")
                        return None

                    try:
                        await self.data_conn.execute(
                            """
                            INSERT INTO chapters
                            (user_id, username, display_name, work_id, chapter, price, approved_by, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, task["username"], task["display_name"], work_id, chapter,
                             task["price"], approved_by, self._now())
                        )
                    except Exception as e:
                        await self.data_conn.execute("ROLLBACK")
                        logger.error(f"Failed to insert chapter: {e}")
                        return None

                    await self.data_conn.execute(
                        '''INSERT INTO logs (action, user_id, target_id, details, timestamp, type)
                           VALUES (?, ?, ?, ?, ?, ?)''',
                        ("financial_approve", approved_by, user_id,
                         json.dumps({"work_id": work_id, "chapter": chapter, "price": task["price"]}),
                         self._now(), "financial")
                    )

                    await self.data_conn.commit()
                    logger.info(f"Approved task {user_id} {work_id} {chapter} with price {task['price']}")
                    return task

            except aiosqlite.OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    await asyncio.sleep(0.2 * (2 ** attempt))
                    continue
                else:
                    await self.data_conn.execute("ROLLBACK")
                    logger.error(f"Approve task error after {attempt+1} attempts: {e}")
                    return None
            except Exception as e:
                await self.data_conn.execute("ROLLBACK")
                logger.error(f"Approve task error: {e}")
                return None
        return None

    async def approve_task_by_name(self, user_id: str, work_name: str, chapter: int, approved_by: str):
        async with self.data_lock:
            work_id = await self._get_work_id_by_name(work_name)
            if not work_id:
                return None
        return await self.approve_task(user_id, work_id, chapter, approved_by)

    async def reject_task(self, user_id: str, work_id: int, chapter: int,
                          rejected_by: str, reason: str):
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                """
                UPDATE tasks
                SET status = 'rejected', rejected_by = ?,
                    rejected_at = ?, reject_reason = ?
                WHERE user_id = ? AND work_id = ? AND chapter = ? AND status = 'submitted'
                """,
                (rejected_by, self._now(), reason, user_id, work_id, chapter)
            )
            await self.data_conn.commit()
            return cursor.rowcount > 0

    async def reject_task_by_name(self, user_id: str, work_name: str, chapter: int,
                                   rejected_by: str, reason: str):
        async with self.data_lock:
            work_id = await self._get_work_id_by_name(work_name)
            if not work_id:
                return False
            return await self.reject_task(user_id, work_id, chapter, rejected_by, reason)

    # ========== الإحصائيات ==========
    async def get_user_stats(self, user_id: str):
        async with self.data_lock:
            cursor = await self.data_conn.execute(
                "SELECT COALESCE(SUM(price), 0) as total, COUNT(*) as count FROM chapters WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            total_earned = row["total"]
            chapters_count = row["count"]

            cursor = await self.data_conn.execute('''
                SELECT c.*, w.name as work_name
                FROM chapters c
                JOIN works w ON c.work_id = w.id
                WHERE c.user_id = ?
                ORDER BY c.created_at DESC
                LIMIT 10
            ''', (user_id,))
            recent_rows = await cursor.fetchall()
            recent_list = [dict(r) for r in recent_rows]

            cursor = await self.data_conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'pending'",
                (user_id,)
            )
            pending = (await cursor.fetchone())[0]

            cursor = await self.data_conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'submitted'",
                (user_id,)
            )
            submitted = (await cursor.fetchone())[0]

            user = await self._get_user(user_id)
            display_name = user["display_name"] if user else None

            return {
                "total_earned": total_earned,
                "chapters_count": chapters_count,
                "recent_chapters": recent_list,
                "pending_tasks": pending,
                "submitted_tasks": submitted,
                "display_name": display_name
            }

    async def get_team_stats(self):
        async with self.data_lock:
            cursor = await self.data_conn.execute("SELECT COUNT(*) FROM chapters")
            total_chapters = (await cursor.fetchone())[0]

            cursor = await self.data_conn.execute("SELECT COALESCE(SUM(price), 0) FROM chapters")
            total_earnings = (await cursor.fetchone())[0]

            cursor = await self.data_conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'")
            pending = (await cursor.fetchone())[0]

            cursor = await self.data_conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'submitted'")
            submitted = (await cursor.fetchone())[0]

            cursor = await self.data_conn.execute('''
                SELECT user_id, username, display_name, COUNT(*) as count, COALESCE(SUM(price), 0) as total
                FROM chapters GROUP BY user_id ORDER BY count DESC LIMIT 5
            ''')
            rows = await cursor.fetchall()
            top_users = [dict(r) for r in rows]
            return {
                "total_chapters": total_chapters,
                "total_earnings": total_earnings,
                "pending_tasks": pending,
                "submitted_tasks": submitted,
                "top_users": top_users
            }

    async def get_weekly_report(self):
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        async with self.data_lock:
            cursor = await self.data_conn.execute('''
                SELECT user_id, username, display_name, COUNT(*) as chapters, COALESCE(SUM(price), 0) as earnings
                FROM chapters WHERE created_at >= ? GROUP BY user_id ORDER BY chapters DESC
            ''', (week_ago,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ========== إدارة السجلات ==========
    async def delete_all_logs(self, user_id: str):
        async with self.data_lock:
            try:
                await self.data_conn.execute("BEGIN IMMEDIATE")
                await self.data_conn.execute("DELETE FROM logs WHERE type != 'financial'")
                await self.data_conn.commit()
            except Exception as e:
                await self.data_conn.execute("ROLLBACK")
                logger.error(f"Error deleting logs: {e}")
                return
        asyncio.create_task(self.log_action("delete_all_logs", user_id, log_type="admin"))

# إنشاء النسخة العامة
db = Database()
