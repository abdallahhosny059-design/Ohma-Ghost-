import aiosqlite
import asyncio
import logging
from datetime import datetime, timedelta
import json
import os
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db_path = "bot_database.db"
        self.conn: Optional[aiosqlite.Connection] = None
        self.lock = asyncio.Lock()
        self.initialized = False

    async def initialize(self):
        if self.initialized:
            return
        try:
            self.conn = await aiosqlite.connect(self.db_path)

            # تحسينات الأداء – مناسبة لبيئة الإنتاج
            await self.conn.execute("PRAGMA foreign_keys = ON;")
            await self.conn.execute("PRAGMA journal_mode = WAL;")
            await self.conn.execute("PRAGMA busy_timeout = 5000;")
            await self.conn.execute("PRAGMA synchronous = NORMAL;")
            await self.conn.execute("PRAGMA cache_size = -2000;")
            await self.conn.execute("PRAGMA temp_store = MEMORY;")
            self.conn.row_factory = aiosqlite.Row

            # إنشاء الجداول (كما هي سليمة)
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
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id TEXT PRIMARY KEY,
                    added_by INTEGER NOT NULL,
                    added_at TEXT NOT NULL
                )
            ''')
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            ''')

            # الفهارس – ضرورية للأداء
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status)
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tasks_work_chapter ON tasks(work, chapter)
            ''')
            await self.conn.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_unique_pending 
                ON tasks(user_id, work, chapter) WHERE status IN ('pending', 'submitted')
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_chapters_user_date ON chapters(user_id, created_at DESC)
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_logs_type ON logs(type)
            ''')
            await self.conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_works_name_active ON works(name, is_active)
            ''')

            await self.conn.commit()
            self.initialized = True
            logger.info("✅ SQLite database connected and optimized")

        except Exception as e:
            logger.error(f"❌ Database initialization error: {e}")
            if self.conn:
                await self.conn.close()
                self.conn = None
            raise

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None
            self.initialized = False
            logger.info("Database connection closed.")

    def _now(self) -> str:
        return datetime.utcnow().isoformat()

    # ==================== دوال المستخدمين ====================
    async def get_or_create_user(self, user_id: str, username: str, display_name: str = None) -> Dict[str, Any]:
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
            cursor = await self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            user = await cursor.fetchone()
        else:
            if display_name and user["display_name"] != display_name:
                await self.conn.execute(
                    "UPDATE users SET display_name = ? WHERE user_id = ?",
                    (display_name, user_id)
                )
                await self.conn.commit()
                cursor = await self.conn.execute(
                    "SELECT * FROM users WHERE user_id = ?", (user_id,)
                )
                user = await cursor.fetchone()
        return dict(user)

    # ==================== المالك ====================
    async def set_owner(self, user_id: int) -> bool:
        async with self.lock:
            cursor = await self.conn.execute(
                "SELECT value FROM settings WHERE key = 'owner_id'"
            )
            if await cursor.fetchone():
                return False
            await self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("owner_id", str(user_id))
            )
            await self.conn.commit()
            return True

    async def get_owner(self) -> Optional[int]:
        cursor = await self.conn.execute(
            "SELECT value FROM settings WHERE key = 'owner_id'"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else None

    # ==================== الأدمن ====================
    async def add_admin(self, user_id: str, added_by: int) -> bool:
        async with self.lock:
            await self.conn.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                (user_id, added_by, self._now())
            )
            cursor = await self.conn.execute("SELECT changes()")
            created = (await cursor.fetchone())[0] == 1
            await self.conn.commit()
            if created:
                await self.log_action("add_admin", added_by, target_id=user_id)
            return created

    async def remove_admin(self, user_id: str) -> bool:
        async with self.lock:
            await self.conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            cursor = await self.conn.execute("SELECT changes()")
            deleted = (await cursor.fetchone())[0] == 1
            await self.conn.commit()
            if deleted:
                await self.log_action("remove_admin", int(user_id) if user_id.isdigit() else 0, target_id=user_id)
            return deleted

    async def is_admin(self, user_id: str) -> bool:
        cursor = await self.conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return await cursor.fetchone() is not None

    async def get_admins(self) -> List[Dict[str, Any]]:
        cursor = await self.conn.execute("SELECT user_id, added_at FROM admins ORDER BY added_at")
        rows = await cursor.fetchall()
        return [{"user_id": row[0], "added_at": row[1]} for row in rows]

    # ==================== الأعمال ====================
    async def add_work(self, name: str, link: str, added_by: int) -> Tuple[bool, str]:
        try:
            async with self.lock:
                await self.conn.execute(
                    '''INSERT INTO works (name, link, added_by, created_at, is_active)
                       VALUES (?, ?, ?, ?, ?)''',
                    (name, link, added_by, self._now(), 1)
                )
                await self.conn.commit()
            await self.log_action("add_work", added_by, details={"name": name, "link": link})
            return True, "✅ تمت الإضافة بنجاح"
        except aiosqlite.IntegrityError:
            return False, "❌ العمل موجود مسبقاً"
        except Exception as e:
            logger.error(f"Error in add_work: {e}")
            return False, "❌ حدث خطأ غير متوقع"

    async def get_work(self, name: str) -> Optional[Dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM works WHERE LOWER(name) = LOWER(?) AND is_active = 1",
            (name,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def search_works(self, query: str) -> List[Dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM works WHERE LOWER(name) LIKE LOWER(?) AND is_active = 1 LIMIT 10",
            (f"%{query}%",)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_work(self, name: str, deleted_by: int) -> Tuple[bool, str]:
        async with self.lock:
            cursor = await self.conn.execute(
                """
                SELECT COUNT(*) FROM tasks
                WHERE work IN (SELECT name FROM works WHERE LOWER(name) = LOWER(?))
                AND status IN ('pending', 'submitted')
                """,
                (name,)
            )
            count = (await cursor.fetchone())[0]
            if count > 0:
                return False, f"❌ لا يمكن حذف العمل لأنه مرتبط بـ {count} مهام نشطة."

            cursor = await self.conn.execute(
                "UPDATE works SET is_active = 0 WHERE LOWER(name) = LOWER(?)",
                (name,)
            )
            deleted = cursor.rowcount > 0
            await self.conn.commit()
            if deleted:
                await self.log_action("delete_work", deleted_by, details={"name": name})
                return True, "✅ تم حذف العمل بنجاح."
            return False, "❌ العمل غير موجود."

    # ==================== المهام ====================
    async def create_task(self, user_id: str, username: str, display_name: str,
                          work: str, chapter: int, price: int, assigned_by: int) -> Tuple[bool, str]:
        if price <= 0 or price > 10000:
            return False, "❌ السعر يجب أن يكون بين 1 و 10000"
        if chapter <= 0:
            return False, "❌ رقم الفصل غير صالح"

        async with self.lock:
            work_doc = await self.get_work(work)
            if not work_doc:
                return False, "❌ العمل غير موجود"

            await self.get_or_create_user(user_id, username, display_name)

            try:
                await self.conn.execute(
                    '''INSERT OR IGNORE INTO tasks
                       (user_id, username, display_name, work, chapter, price,
                        status, assigned_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id, username, display_name, work_doc["name"], chapter, price,
                     "pending", assigned_by, self._now())
                )

                cursor = await self.conn.execute("SELECT changes()")
                created = (await cursor.fetchone())[0] == 1
                await self.conn.commit()

                if not created:
                    return False, "❌ هذا الفصل مكلف بالفعل لهذا العضو"
            except Exception as e:
                logger.error(f"Error creating task: {e}")
                return False, "❌ حدث خطأ أثناء إنشاء المهمة"

        await self.log_action(
            "create_task", assigned_by, target_id=user_id,
            details={"work": work_doc["name"], "chapter": chapter, "price": price}
        )
        return True, "✅ تم التكليف بنجاح"

    async def get_user_tasks(self, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status:
            cursor = await self.conn.execute(
                """
                SELECT tasks.* FROM tasks
                INNER JOIN works ON tasks.work = works.name
                WHERE tasks.user_id = ? AND tasks.status = ? AND works.is_active = 1
                ORDER BY tasks.created_at DESC
                """,
                (user_id, status)
            )
        else:
            cursor = await self.conn.execute(
                """
                SELECT tasks.* FROM tasks
                INNER JOIN works ON tasks.work = works.name
                WHERE tasks.user_id = ? AND works.is_active = 1
                ORDER BY tasks.created_at DESC
                """,
                (user_id,)
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def submit_task(self, user_id: str, work: str, chapter: int) -> bool:
        async with self.lock:
            await self.conn.execute(
                """
                UPDATE tasks
                SET status = ?, submitted_at = ?
                WHERE user_id = ? AND work IN (SELECT name FROM works WHERE LOWER(name) = LOWER(?)) AND chapter = ? AND status = 'pending'
                """,
                ("submitted", self._now(), user_id, work, chapter)
            )
            # استخدام SELECT changes() بدلاً من rowcount
            cursor = await self.conn.execute("SELECT changes()")
            changes = (await cursor.fetchone())[0]
            await self.conn.commit()
            success = changes == 1
            if success:
                await self.log_action("submit_task", int(user_id), details={"work": work, "chapter": chapter})
            return success

    async def approve_task(self, user_id: str, work: str, chapter: int, approved_by: int) -> Optional[Dict[str, Any]]:
        async with self.lock:
            # نبدأ المعاملة يدويًا لضمان atomicity
            try:
                await self.conn.execute("BEGIN")

                # 1. البحث عن المهمة باستخدام الاسم الأصلي (case-insensitive)
                cursor = await self.conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE user_id = ? AND work IN (SELECT name FROM works WHERE LOWER(name) = LOWER(?)) AND chapter = ?
                      AND status = 'submitted' AND approved_at IS NULL
                    """,
                    (user_id, work, chapter)
                )
                task = await cursor.fetchone()
                if not task:
                    await self.conn.execute("ROLLBACK")
                    return None

                # 2. تحديث حالة المهمة إلى approved
                await self.conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'approved', approved_by = ?, approved_at = ?
                    WHERE id = ?
                    """,
                    (approved_by, self._now(), task["id"])
                )

                # 3. إدراج السجل في chapters مع استخدام اسم العمل الأصلي من المهمة
                try:
                    await self.conn.execute(
                        """
                        INSERT INTO chapters
                        (user_id, username, display_name, work, chapter, price, approved_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, task["username"], task["display_name"], task["work"], chapter,
                         task["price"], approved_by, self._now())
                    )
                except aiosqlite.IntegrityError:
                    # تكرار – نتراجع عن كل شيء
                    await self.conn.execute("ROLLBACK")
                    return None

                # 4. commit المعاملة
                await self.conn.commit()

                # 5. إعادة جلب المهمة المحدثة (للحصول على approved_at, approved_by)
                cursor = await self.conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task["id"],)
                )
                updated_task = await cursor.fetchone()

                # 6. تسجيل العملية المالية (يمكن جعله جزءًا من المعاملة لكننا نفضل فصله لتجنب إبطاء المعاملة)
                await self.log_action(
                    "financial_approve", approved_by, target_id=user_id,
                    details={"work": task["work"], "chapter": chapter, "price": task["price"]},
                    log_type="financial"
                )
                return dict(updated_task) if updated_task else None

            except Exception as e:
                # أي خطأ غير متوقع – نتراجع ونُعلم
                await self.conn.execute("ROLLBACK")
                logger.error(f"Error in approve_task: {e}")
                return None

    async def reject_task(self, user_id: str, work: str, chapter: int,
                          rejected_by: int, reason: str) -> bool:
        async with self.lock:
            await self.conn.execute(
                """
                UPDATE tasks
                SET status = 'rejected', rejected_by = ?,
                    rejected_at = ?, reject_reason = ?
                WHERE user_id = ? AND work IN (SELECT name FROM works WHERE LOWER(name) = LOWER(?)) AND chapter = ? AND status = 'submitted'
                """,
                (rejected_by, self._now(), reason, user_id, work, chapter)
            )
            cursor = await self.conn.execute("SELECT changes()")
            changes = (await cursor.fetchone())[0]
            await self.conn.commit()
            success = changes == 1
            if success:
                await self.log_action(
                    "reject_task", rejected_by, target_id=user_id,
                    details={"work": work, "chapter": chapter, "reason": reason}
                )
            return success

    # ==================== الإحصائيات ====================
    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
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
        user_row = await cursor.fetchone()
        display_name = user_row["display_name"] if user_row else None

        return {
            "total_earned": total_earned,
            "chapters_count": chapters_count,
            "recent_chapters": [dict(r) for r in recent],
            "pending_tasks": pending,
            "submitted_tasks": submitted,
            "display_name": display_name
        }

    async def get_team_stats(self) -> Dict[str, Any]:
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
            FROM chapters
            GROUP BY user_id
            ORDER BY count DESC
            LIMIT 5
        ''')
        top_users = await cursor.fetchall()

        return {
            "total_chapters": total_chapters,
            "total_earnings": total_earnings,
            "pending_tasks": pending,
            "submitted_tasks": submitted,
            "top_users": [dict(u) for u in top_users]
        }

    async def get_weekly_report(self) -> List[Dict[str, Any]]:
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        cursor = await self.conn.execute('''
            SELECT user_id, username, display_name, COUNT(*) as chapters, COALESCE(SUM(price), 0) as earnings
            FROM chapters
            WHERE created_at >= ?
            GROUP BY user_id
            ORDER BY chapters DESC
        ''', (week_ago,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ==================== التسجيل ====================
    async def log_action(self, action: str, user_id: int, target_id: Optional[str] = None,
                         details: Optional[Dict] = None, log_type: str = "normal"):
        """تسجيل حدث مع commit منفصل (للأحداث غير المالية)."""
        await self.conn.execute(
            '''INSERT INTO logs (action, user_id, target_id, details, timestamp, type)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (action, user_id, target_id, json.dumps(details or {}), self._now(), log_type)
        )
        await self.conn.commit()

    # يمكن إضافة دالة log_action_no_commit إذا أردنا تضمينها في المعاملات الكبيرة.

    async def delete_all_logs(self, user_id: int):
        async with self.lock:
            try:
                await self.conn.execute("BEGIN")
                await self.conn.execute(
                    """INSERT INTO logs (action, user_id, timestamp, type) VALUES (?, ?, ?, ?)""",
                    ("delete_all_logs", user_id, self._now(), "admin")
                )
                await self.conn.execute("DELETE FROM logs WHERE type != 'financial'")
                await self.conn.commit()
            except Exception as e:
                await self.conn.execute("ROLLBACK")
                logger.error(f"Error deleting logs: {e}")

# ========== إنشاء النسخة العامة ==========
db = Database()
