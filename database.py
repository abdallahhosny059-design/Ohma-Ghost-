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
        self.write_conn = None
        self.read_pool_size = 5
        self.read_queue = asyncio.Queue()
        self._read_conns = []                # للتنظيف عند الفشل
        self.write_lock = asyncio.Lock()
        self.init_lock = asyncio.Lock()
        self.log_queue = asyncio.Queue(maxsize=2000)
        self.log_worker_task = None
        self.initialized = False

    # -----------------------------------------------------------
    # التهيئة والإغلاق
    # -----------------------------------------------------------
    async def initialize(self):
        async with self.init_lock:
            if self.initialized:
                return

            try:
                # إنشاء اتصال الكتابة
                self.write_conn = await aiosqlite.connect(self.db_path)
                await self.write_conn.execute("PRAGMA foreign_keys = ON;")
                await self.write_conn.execute("PRAGMA journal_mode = WAL;")
                await self.write_conn.execute("PRAGMA busy_timeout = 5000;")
                await self.write_conn.execute("PRAGMA synchronous = NORMAL;")
                await self.write_conn.execute("PRAGMA cache_size = -2000;")
                await self.write_conn.execute("PRAGMA temp_store = MEMORY;")
                await self.write_conn.execute("PRAGMA wal_autocheckpoint = 1000;")
                self.write_conn.row_factory = aiosqlite.Row

                # إنشاء اتصالات القراءة (بدون WAL – غير ضروري)
                for _ in range(self.read_pool_size):
                    conn = await aiosqlite.connect(self.db_path)
                    await conn.execute("PRAGMA busy_timeout = 5000;")
                    await conn.execute("PRAGMA synchronous = NORMAL;")
                    conn.row_factory = aiosqlite.Row
                    self._read_conns.append(conn)
                    await self.read_queue.put(conn)

                # إنشاء الجداول والفهارس
                await self._create_tables()

                # بدء معالج السجلات
                self.log_worker_task = asyncio.create_task(self._log_worker())

                self.initialized = True
                logger.info("✅ Database ready – final production version")

            except Exception as e:
                logger.error(f"❌ Database init error: {e}")
                await self._cleanup()
                raise

    async def _create_tables(self):
        """إنشاء الجداول والفهارس (تُستدعى مرة واحدة)."""
        await self.write_conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                display_name TEXT,
                joined_at TEXT NOT NULL,
                is_banned INTEGER DEFAULT 0
            )
        ''')
        await self.write_conn.execute('''
            CREATE TABLE IF NOT EXISTS works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                link TEXT NOT NULL,
                added_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        ''')
        await self.write_conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_works_name ON works(name COLLATE NOCASE)
        ''')
        await self.write_conn.execute('''
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
        await self.write_conn.execute('''
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
        await self.write_conn.execute('''
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
        await self.write_conn.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id TEXT PRIMARY KEY,
                added_by TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
        ''')
        await self.write_conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')

        # فهارس إضافية
        await self.write_conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status)
        ''')
        await self.write_conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_tasks_work_id ON tasks(work_id)
        ''')
        await self.write_conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_task_unique_pending 
            ON tasks(user_id, work_id, chapter) WHERE status IN ('pending', 'submitted')
        ''')
        await self.write_conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_chapters_user_date ON chapters(user_id, created_at DESC)
        ''')
        await self.write_conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_chapters_work_id ON chapters(work_id)
        ''')
        await self.write_conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)
        ''')
        await self.write_conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_logs_type ON logs(type)
        ''')
        await self.write_conn.commit()

    async def close(self):
        """إغلاق جميع الاتصالات وانتظار السجلات المتبقية بأمان."""
        if not self.initialized:
            return

        # انتظار معالجة كل السجلات (task_done سيتم استدعاؤها بعد الكتابة)
        if self.log_worker_task and not self.log_worker_task.done():
            await self.log_queue.join()
            self.log_worker_task.cancel()
            try:
                await self.log_worker_task
            except asyncio.CancelledError:
                pass

        # إغلاق اتصال الكتابة
        if self.write_conn:
            await self.write_conn.close()

        # إغلاق جميع اتصالات القراءة (من القائمة المحفوظة)
        for conn in self._read_conns:
            try:
                await conn.close()
            except:
                pass

        self.initialized = False
        logger.info("Database closed.")

    async def _cleanup(self):
        """تنظيف في حالة فشل التهيئة."""
        if self.write_conn:
            await self.write_conn.close()
        for conn in self._read_conns:
            try:
                await conn.close()
            except:
                pass
        self._read_conns.clear()

    # -----------------------------------------------------------
    # إدارة اتصالات القراءة (Pool حقيقي)
    # -----------------------------------------------------------
    async def _get_read_conn(self):
        return await self.read_queue.get()

    async def _release_read_conn(self, conn):
        await self.read_queue.put(conn)

    async def _fetchone(self, sql: str, params: tuple = ()):
        if not self.initialized:
            await self.initialize()
        conn = await self._get_read_conn()
        try:
            cursor = await conn.execute(sql, params)
            row = await cursor.fetchone()
            await cursor.close()
            return row
        finally:
            await self._release_read_conn(conn)

    async def _fetchall(self, sql: str, params: tuple = ()):
        if not self.initialized:
            await self.initialize()
        conn = await self._get_read_conn()
        try:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            await cursor.close()
            return rows
        finally:
            await self._release_read_conn(conn)

    # -----------------------------------------------------------
    # نظام السجلات (Batching + إغلاق آمن)
    # -----------------------------------------------------------
    async def _log_worker(self):
        """معالج خلفي لكتابة السجلات بشكل مجمع."""
        batch = []
        last_flush = asyncio.get_event_loop().time()
        while True:
            try:
                entry = await asyncio.wait_for(self.log_queue.get(), timeout=0.5)
                batch.append(entry)
                # لا نستدعي task_done هنا، سنستدعيها بعد الكتابة
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Log worker error: {e}")
                await asyncio.sleep(1)
                continue

            now = asyncio.get_event_loop().time()
            if len(batch) >= 50 or (now - last_flush) >= 1.0:
                if batch:
                    await self._flush_log_batch(batch)
                    # الآن نستدعي task_done لكل عنصر
                    for _ in batch:
                        self.log_queue.task_done()
                    batch.clear()
                    last_flush = now

        # عند الخروج، اكتب أي سجلات متبقية
        if batch:
            await self._flush_log_batch(batch)
            for _ in batch:
                self.log_queue.task_done()

    async def _flush_log_batch(self, batch):
        """كتابة دفعة سجلات مع write_lock."""
        async with self.write_lock:
            try:
                await self.write_conn.executemany(
                    '''INSERT INTO logs (action, user_id, target_id, details, timestamp, type)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    [
                        (action, user_id, target_id,
                         json.dumps(details or {}, ensure_ascii=False),
                         self._now(), log_type)
                        for (action, user_id, target_id, details, log_type) in batch
                    ]
                )
                await self.write_conn.commit()
            except Exception as e:
                logger.error(f"Failed to flush log batch: {e}")
                # في حالة الفشل، نفضل فقدان السجلات بدلاً من تعطيل النظام

    async def _enqueue_log(self, action: str, user_id: str, target_id: str = None,
                           details: dict = None, log_type: str = "normal"):
        """إضافة سجل إلى قائمة الانتظار (المالية لا تُفقد)."""
        if not self.initialized:
            await self.initialize()
        try:
            if log_type == "financial":
                await self.log_queue.put((action, user_id, target_id, details, log_type))
            else:
                self.log_queue.put_nowait((action, user_id, target_id, details, log_type))
        except asyncio.QueueFull:
            if log_type == "financial":
                logger.critical("Financial log queue full! Data may be lost.")

    def _now(self):
        return datetime.utcnow().isoformat()

    # -----------------------------------------------------------
    # owner
    # -----------------------------------------------------------
    async def get_owner_id(self) -> str | None:
        row = await self._fetchone("SELECT value FROM settings WHERE key = 'owner_id'")
        return row["value"] if row else None

    async def set_owner_id(self, owner_id: str):
        if not self.initialized:
            await self.initialize()
        async with self.write_lock:
            await self.write_conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('owner_id', ?)",
                (owner_id,)
            )
            await self.write_conn.commit()

    # -----------------------------------------------------------
    # admin
    # -----------------------------------------------------------
    async def add_admin(self, user_id: str, added_by: str) -> bool:
        if not self.initialized:
            await self.initialize()
        async with self.write_lock:
            cursor = await self.write_conn.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                (user_id, added_by, self._now())
            )
            await self.write_conn.commit()
            success = cursor.rowcount > 0
        if success:
            await self._enqueue_log("add_admin", added_by, target_id=user_id)
        return success

    async def remove_admin(self, user_id: str, removed_by: str) -> bool:
        if not self.initialized:
            await self.initialize()
        async with self.write_lock:
            cursor = await self.write_conn.execute(
                "DELETE FROM admins WHERE user_id = ?", (user_id,)
            )
            await self.write_conn.commit()
            success = cursor.rowcount > 0
        if success:
            await self._enqueue_log("remove_admin", removed_by, target_id=user_id)
        return success

    async def is_admin(self, user_id: str) -> bool:
        row = await self._fetchone("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return row is not None

    async def get_admins(self):
        rows = await self._fetchall("SELECT user_id, added_at FROM admins ORDER BY added_at")
        return [{"user_id": row[0], "added_at": row[1]} for row in rows]

    # -----------------------------------------------------------
    # works
    # -----------------------------------------------------------
    async def add_work(self, name: str, link: str, added_by: str) -> tuple[bool, str]:
        if not self.initialized:
            await self.initialize()
        try:
            async with self.write_lock:
                await self.write_conn.execute(
                    '''INSERT INTO works (name, link, added_by, created_at, is_active)
                       VALUES (?, ?, ?, ?, ?)''',
                    (name, link, added_by, self._now(), 1)
                )
                await self.write_conn.commit()
            await self._enqueue_log("add_work", added_by, details={"name": name, "link": link})
            return True, "✅ تمت الإضافة"
        except Exception:
            return False, "❌ العمل موجود مسبقاً"

    async def get_work_by_name(self, name: str):
        return await self._fetchone(
            "SELECT * FROM works WHERE name = ? COLLATE NOCASE AND is_active = 1", (name,)
        )

    async def get_work_by_id(self, work_id: int):
        return await self._fetchone("SELECT * FROM works WHERE id = ?", (work_id,))

    async def search_works(self, query: str):
        rows = await self._fetchall(
            "SELECT * FROM works WHERE name LIKE ? COLLATE NOCASE AND is_active = 1 LIMIT 10",
            (query + "%",)
        )
        return [dict(row) for row in rows]

    async def delete_work(self, name: str, deleted_by: str) -> bool:
        if not self.initialized:
            await self.initialize()
        async with self.write_lock:
            cursor = await self.write_conn.execute(
                "UPDATE works SET is_active = 0 WHERE name = ? COLLATE NOCASE AND is_active = 1",
                (name,)
            )
            await self.write_conn.commit()
            success = cursor.rowcount > 0
        if success:
            await self._enqueue_log("delete_work", deleted_by, details={"name": name})
        return success

    # -----------------------------------------------------------
    # tasks
    # -----------------------------------------------------------
    async def create_task(self, user_id: str, username: str, display_name: str,
                          work_name: str, chapter: int, price: int, assigned_by: str) -> tuple[bool, str]:
        if not self.initialized:
            await self.initialize()
        if price <= 0 or price > 10000:
            return False, "❌ السعر يجب أن يكون بين 1 و 10000"
        if chapter <= 0:
            return False, "❌ رقم الفصل غير صالح"

        async with self.write_lock:
            work = await self.write_conn.execute(
                "SELECT id FROM works WHERE name = ? COLLATE NOCASE AND is_active = 1",
                (work_name,)
            )
            work_row = await work.fetchone()
            await work.close()
            if not work_row:
                return False, "❌ العمل غير موجود"
            work_id = work_row["id"]

            await self.write_conn.execute(
                '''INSERT OR IGNORE INTO users (user_id, username, display_name, joined_at, is_banned)
                   VALUES (?, ?, ?, ?, ?)''',
                (user_id, username, display_name or username, self._now(), 0)
            )

            try:
                cursor = await self.write_conn.execute(
                    '''INSERT OR IGNORE INTO tasks
                       (user_id, username, display_name, work_id, chapter, price,
                        status, assigned_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id, username, display_name, work_id, chapter, price,
                     "pending", assigned_by, self._now())
                )
                await self.write_conn.commit()
                changes = await self.write_conn.execute("SELECT changes()")
                row_count = (await changes.fetchone())[0]
                if row_count > 0:
                    await self._enqueue_log(
                        "create_task", assigned_by, target_id=user_id,
                        details={"work_id": work_id, "chapter": chapter, "price": price}
                    )
                    return True, "✅ تم التكليف"
                else:
                    return False, "❌ هذا الفصل مكلف بالفعل"
            except Exception as e:
                await self.write_conn.rollback()
                logger.error(f"Error creating task: {e}")
                return False, "❌ حدث خطأ"

    async def get_user_tasks(self, user_id: str, status: str = None):
        if status:
            rows = await self._fetchall('''
                SELECT t.*, w.name as work_name
                FROM tasks t
                JOIN works w ON t.work_id = w.id
                WHERE t.user_id = ? AND t.status = ?
                ORDER BY t.created_at DESC
            ''', (user_id, status))
        else:
            rows = await self._fetchall('''
                SELECT t.*, w.name as work_name
                FROM tasks t
                JOIN works w ON t.work_id = w.id
                WHERE t.user_id = ?
                ORDER BY t.created_at DESC
            ''', (user_id,))
        return [dict(row) for row in rows]

    async def submit_task(self, user_id: str, work_id: int, chapter: int) -> bool:
        if not self.initialized:
            await self.initialize()
        async with self.write_lock:
            cursor = await self.write_conn.execute(
                """
                UPDATE tasks
                SET status = ?, submitted_at = ?
                WHERE user_id = ? AND work_id = ? AND chapter = ? AND status = 'pending'
                """,
                ("submitted", self._now(), user_id, work_id, chapter)
            )
            await self.write_conn.commit()
            return cursor.rowcount > 0

    async def submit_task_by_name(self, user_id: str, work_name: str, chapter: int) -> bool:
        work = await self.get_work_by_name(work_name)
        if not work:
            return False
        return await self.submit_task(user_id, work["id"], chapter)

    async def approve_task(self, user_id: str, work_id: int, chapter: int, approved_by: str) -> dict | None:
        if not self.initialized:
            await self.initialize()
        async with self.write_lock:
            try:
                await self.write_conn.execute("BEGIN IMMEDIATE")

                cursor = await self.write_conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE user_id = ? AND work_id = ? AND chapter = ?
                      AND status = 'submitted' AND approved_at IS NULL
                    """,
                    (user_id, work_id, chapter)
                )
                task_row = await cursor.fetchone()
                await cursor.close()
                if not task_row:
                    await self.write_conn.execute("ROLLBACK")
                    return None

                task = dict(task_row)

                if task["price"] is None or task["price"] <= 0:
                    await self.write_conn.execute("ROLLBACK")
                    logger.error(f"Task {task['id']} invalid price")
                    return None

                await self.write_conn.execute(
                    "UPDATE tasks SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
                    (approved_by, self._now(), task["id"])
                )

                # استخدام INSERT OR IGNORE لتجنب الفشل إذا كان الفصل موجودًا بالفعل
                await self.write_conn.execute(
                    """
                    INSERT OR IGNORE INTO chapters
                    (user_id, username, display_name, work_id, chapter, price, approved_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, task["username"], task["display_name"], work_id, chapter,
                     task["price"], approved_by, self._now())
                )

                changes = await self.write_conn.execute("SELECT changes()")
                inserted = (await changes.fetchone())[0]

                if inserted == 0:
                    # الفصل موجود بالفعل – لا يمكن الموافقة مرة أخرى
                    await self.write_conn.execute("ROLLBACK")
                    logger.warning(f"Chapter already exists for {user_id} {work_id} {chapter}")
                    return None

                await self.write_conn.commit()

                # تسجيل خارج المعاملة
                await self._enqueue_log(
                    "financial_approve", approved_by, target_id=user_id,
                    details={"work_id": work_id, "chapter": chapter, "price": task["price"]},
                    log_type="financial"
                )
                return task

            except Exception as e:
                await self.write_conn.execute("ROLLBACK")
                logger.error(f"Approve task error: {e}")
                return None

    async def approve_task_by_name(self, user_id: str, work_name: str, chapter: int, approved_by: str) -> dict | None:
        work = await self.get_work_by_name(work_name)
        if not work:
            return None
        return await self.approve_task(user_id, work["id"], chapter, approved_by)

    async def reject_task(self, user_id: str, work_id: int, chapter: int,
                          rejected_by: str, reason: str) -> bool:
        if not self.initialized:
            await self.initialize()
        async with self.write_lock:
            cursor = await self.write_conn.execute(
                """
                UPDATE tasks
                SET status = 'rejected', rejected_by = ?,
                    rejected_at = ?, reject_reason = ?
                WHERE user_id = ? AND work_id = ? AND chapter = ? AND status = 'submitted'
                """,
                (rejected_by, self._now(), reason, user_id, work_id, chapter)
            )
            await self.write_conn.commit()
            return cursor.rowcount > 0

    async def reject_task_by_name(self, user_id: str, work_name: str, chapter: int,
                                   rejected_by: str, reason: str) -> bool:
        work = await self.get_work_by_name(work_name)
        if not work:
            return False
        return await self.reject_task(user_id, work["id"], chapter, rejected_by, reason)

    # -----------------------------------------------------------
    # stats
    # -----------------------------------------------------------
    async def get_user_stats(self, user_id: str):
        total = await self._fetchone(
            "SELECT COALESCE(SUM(price), 0) as total, COUNT(*) as count FROM chapters WHERE user_id = ?",
            (user_id,)
        )
        total_earned = total["total"]
        chapters_count = total["count"]

        recent_rows = await self._fetchall('''
            SELECT c.*, w.name as work_name
            FROM chapters c
            JOIN works w ON c.work_id = w.id
            WHERE c.user_id = ?
            ORDER BY c.created_at DESC
            LIMIT 10
        ''', (user_id,))
        recent_list = [dict(row) for row in recent_rows]

        pending = (await self._fetchone(
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'pending'",
            (user_id,)
        ))[0]

        submitted = (await self._fetchone(
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'submitted'",
            (user_id,)
        ))[0]

        user = await self._fetchone(
            "SELECT display_name FROM users WHERE user_id = ?", (user_id,)
        )
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
        total_chapters = (await self._fetchone("SELECT COUNT(*) FROM chapters"))[0]
        total_earnings = (await self._fetchone("SELECT COALESCE(SUM(price), 0) FROM chapters"))[0]
        pending = (await self._fetchone("SELECT COUNT(*) FROM tasks WHERE status = 'pending'"))[0]
        submitted = (await self._fetchone("SELECT COUNT(*) FROM tasks WHERE status = 'submitted'"))[0]

        rows = await self._fetchall('''
            SELECT user_id, username, display_name, COUNT(*) as count, COALESCE(SUM(price), 0) as total
            FROM chapters GROUP BY user_id ORDER BY count DESC LIMIT 5
        ''')
        top_users = [dict(row) for row in rows]
        return {
            "total_chapters": total_chapters,
            "total_earnings": total_earnings,
            "pending_tasks": pending,
            "submitted_tasks": submitted,
            "top_users": top_users
        }

    async def get_weekly_report(self):
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        rows = await self._fetchall('''
            SELECT user_id, username, display_name, COUNT(*) as chapters, COALESCE(SUM(price), 0) as earnings
            FROM chapters WHERE created_at >= ? GROUP BY user_id ORDER BY chapters DESC
        ''', (week_ago,))
        return [dict(row) for row in rows]

    # -----------------------------------------------------------
    # logs management
    # -----------------------------------------------------------
    async def delete_all_logs(self, user_id: str):
        if not self.initialized:
            await self.initialize()
        async with self.write_lock:
            try:
                await self.write_conn.execute("BEGIN IMMEDIATE")
                await self.write_conn.execute("DELETE FROM logs WHERE type != 'financial'")
                await self.write_conn.commit()
            except Exception as e:
                await self.write_conn.execute("ROLLBACK")
                logger.error(f"Error deleting logs: {e}")
                return
        await self._enqueue_log("delete_all_logs", user_id, log_type="admin")


# -----------------------------------------------------------
# النسخة العامة
# -----------------------------------------------------------
db = Database()
