import aiosqlite
import asyncio
import logging
from datetime import datetime, timedelta
import pytz
import json
import os

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db_path = "/data/bot_database.db"  # Railway Volume path
        self.initialized = False
    
    async def initialize(self):
        if self.initialized:
            return
        
        try:
            # Ensure data directory exists
            os.makedirs("/data", exist_ok=True)
            
            async with aiosqlite.connect(self.db_path) as db:
                # Enable foreign keys
                await db.execute("PRAGMA foreign_keys = ON;")
                
                # Enable WAL mode for better concurrency
                await db.execute("PRAGMA journal_mode = WAL;")
                
                # Create tables
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        username TEXT NOT NULL,
                        display_name TEXT,
                        joined_at TIMESTAMP NOT NULL,
                        is_banned INTEGER DEFAULT 0
                    )
                ''')
                
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS works (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        link TEXT NOT NULL,
                        added_by INTEGER NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        is_active INTEGER DEFAULT 1
                    )
                ''')
                
                await db.execute('''
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
                        created_at TIMESTAMP NOT NULL,
                        submitted_at TIMESTAMP,
                        approved_at TIMESTAMP,
                        rejected_at TIMESTAMP,
                        approved_by INTEGER,
                        rejected_by INTEGER,
                        reject_reason TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
                        FOREIGN KEY (work) REFERENCES works (name) ON DELETE RESTRICT,
                        UNIQUE(user_id, work, chapter, status) 
                        WHERE status IN ('pending', 'submitted')
                    )
                ''')
                
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS chapters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        username TEXT NOT NULL,
                        display_name TEXT,
                        work TEXT NOT NULL,
                        chapter INTEGER NOT NULL,
                        price INTEGER NOT NULL,
                        approved_by INTEGER NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
                        FOREIGN KEY (work) REFERENCES works (name) ON DELETE RESTRICT,
                        UNIQUE(user_id, work, chapter)
                    )
                ''')
                
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        target_id TEXT,
                        details TEXT,
                        timestamp TIMESTAMP NOT NULL,
                        type TEXT DEFAULT 'normal'
                    )
                ''')
                
                # Create indexes for performance
                await db.execute('''
                    CREATE INDEX IF NOT EXISTS idx_tasks_user_status 
                    ON tasks(user_id, status)
                ''')
                
                await db.execute('''
                    CREATE INDEX IF NOT EXISTS idx_tasks_work_chapter 
                    ON tasks(work, chapter)
                ''')
                
                await db.execute('''
                    CREATE INDEX IF NOT EXISTS idx_chapters_user_date 
                    ON chapters(user_id, created_at DESC)
                ''')
                
                await db.execute('''
                    CREATE INDEX IF NOT EXISTS idx_logs_timestamp 
                    ON logs(timestamp)
                ''')
                
                await db.execute('''
                    CREATE INDEX IF NOT EXISTS idx_logs_type 
                    ON logs(type)
                ''')
                
                await db.commit()
            
            self.initialized = True
            logger.info("✅ SQLite database connected and optimized")
            
        except Exception as e:
            logger.error(f"❌ Database error: {e}")
            raise
    
    # ========== User Operations ==========
    async def get_or_create_user(self, user_id: str, username: str, display_name: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,)
            )
            user = await cursor.fetchone()
            
            if not user:
                await db.execute(
                    '''INSERT INTO users (user_id, username, display_name, joined_at, is_banned)
                       VALUES (?, ?, ?, ?, ?)''',
                    (user_id, username, display_name or username, datetime.now(pytz.UTC), 0)
                )
                await db.commit()
                
                return {
                    "user_id": user_id,
                    "username": username,
                    "display_name": display_name or username,
                    "joined_at": datetime.now(pytz.UTC),
                    "is_banned": False
                }
            
            # Update display name if changed
            if display_name and user["display_name"] != display_name:
                await db.execute(
                    "UPDATE users SET display_name = ? WHERE user_id = ?",
                    (display_name, user_id)
                )
                await db.commit()
            
            return dict(user)
    
    # ========== Work Operations ==========
    async def add_work(self, name: str, link: str, added_by: int):
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = ON;")
                
                await db.execute(
                    '''INSERT INTO works (name, link, added_by, created_at, is_active)
                       VALUES (?, ?, ?, ?, ?)''',
                    (name, link, added_by, datetime.now(pytz.UTC), 1)
                )
                await db.commit()
                
                await self.log_action("add_work", added_by, details={"name": name, "link": link})
                return True, "✅ تمت الإضافة"
        except Exception as e:
            return False, "❌ العمل موجود مسبقاً"
    
    async def get_work(self, name: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM works WHERE LOWER(name) = LOWER(?) AND is_active = 1",
                (name,)
            )
            return await cursor.fetchone()
    
    async def search_works(self, query: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM works WHERE LOWER(name) LIKE LOWER(?) AND is_active = 1 LIMIT 10",
                (f"%{query}%",)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def delete_work(self, name: str, deleted_by: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            
            cursor = await db.execute(
                "UPDATE works SET is_active = 0 WHERE LOWER(name) = LOWER(?)",
                (name,)
            )
            if cursor.rowcount > 0:
                await db.commit()
                await self.log_action("delete_work", deleted_by, details={"name": name})
                return True
            return False
    
    # ========== Task Operations ==========
    async def create_task(self, user_id: str, username: str, display_name: str,
                         work: str, chapter: int, price: int, assigned_by: int):
        # Validate inputs
        if price <= 0 or price > 10000:
            return False, "❌ السعر يجب أن يكون بين 1 و 10000"
        
        if chapter <= 0:
            return False, "❌ رقم الفصل غير صالح"
        
        # Check if work exists
        work_doc = await self.get_work(work)
        if not work_doc:
            return False, "❌ العمل غير موجود"
        
        # Get or create user
        await self.get_or_create_user(user_id, username, display_name)
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = ON;")
                
                # Check for existing pending/submitted task
                cursor = await db.execute(
                    '''SELECT id FROM tasks 
                       WHERE user_id = ? AND work = ? AND chapter = ? 
                       AND status IN ('pending', 'submitted')''',
                    (user_id, work_doc["name"], chapter)
                )
                if await cursor.fetchone():
                    return False, "❌ هذا الفصل مكلف بالفعل"
                
                await db.execute(
                    '''INSERT INTO tasks 
                       (user_id, username, display_name, work, chapter, price, 
                        status, assigned_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id, username, display_name, work_doc["name"], chapter, price,
                     "pending", assigned_by, datetime.now(pytz.UTC))
                )
                await db.commit()
                
                await self.log_action(
                    "create_task", assigned_by, target_id=user_id,
                    details={"work": work_doc["name"], "chapter": chapter, "price": price}
                )
                return True, "✅ تم التكليف"
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            return False, "❌ حدث خطأ"
    
    async def get_user_tasks(self, user_id: str, status: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            
            if status:
                cursor = await db.execute(
                    "SELECT * FROM tasks WHERE user_id = ? AND status = ? ORDER BY created_at DESC",
                    (user_id, status)
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,)
                )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def submit_task(self, user_id: str, work: str, chapter: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            
            cursor = await db.execute(
                '''UPDATE tasks SET status = ?, submitted_at = ?
                   WHERE user_id = ? AND work = ? AND chapter = ? AND status = 'pending'''',
                ("submitted", datetime.now(pytz.UTC), user_id, work, chapter)
            )
            await db.commit()
            
            success = cursor.rowcount > 0
            await self.log_action(
                "submit_task", int(user_id),
                details={"work": work, "chapter": chapter, "success": success}
            )
            return success
    
    async def approve_task(self, user_id: str, work: str, chapter: int, approved_by: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            
            # Start transaction
            await db.execute("BEGIN")
            
            try:
                # Get and lock the task
                cursor = await db.execute(
                    '''SELECT * FROM tasks 
                       WHERE user_id = ? AND work = ? AND chapter = ? 
                       AND status = 'submitted' AND approved_at IS NULL''',
                    (user_id, work, chapter)
                )
                task = await cursor.fetchone()
                
                if not task:
                    await db.execute("ROLLBACK")
                    return None
                
                # Update task
                await db.execute(
                    '''UPDATE tasks SET status = 'approved', approved_by = ?, approved_at = ?
                       WHERE id = ?''',
                    (approved_by, datetime.now(pytz.UTC), task["id"])
                )
                
                # Insert chapter
                await db.execute(
                    '''INSERT INTO chapters 
                       (user_id, username, display_name, work, chapter, price, approved_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id, task["username"], task["display_name"], work, chapter,
                     task["price"], approved_by, datetime.now(pytz.UTC))
                )
                
                # Commit transaction
                await db.commit()
                
                await self.log_action(
                    "financial_approve", approved_by, target_id=user_id,
                    details={"work": work, "chapter": chapter, "price": task["price"]},
                    log_type="financial"
                )
                
                return dict(task)
                
            except Exception as e:
                await db.execute("ROLLBACK")
                logger.error(f"Error in approve_task: {e}")
                return None
    
    async def reject_task(self, user_id: str, work: str, chapter: int,
                         rejected_by: int, reason: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            
            cursor = await db.execute(
                '''UPDATE tasks SET status = 'rejected', rejected_by = ?,
                   rejected_at = ?, reject_reason = ?
                   WHERE user_id = ? AND work = ? AND chapter = ? AND status = 'submitted'''',
                (rejected_by, datetime.now(pytz.UTC), reason, user_id, work, chapter)
            )
            await db.commit()
            
            if cursor.rowcount > 0:
                await self.log_action(
                    "reject_task", rejected_by, target_id=user_id,
                    details={"work": work, "chapter": chapter, "reason": reason}
                )
                return True
            return False
    
    # ========== Stats Operations ==========
    async def get_user_stats(self, user_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            
            # Get totals
            cursor = await db.execute(
                "SELECT COALESCE(SUM(price), 0) as total, COUNT(*) as count FROM chapters WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            # Recent chapters
            cursor = await db.execute(
                "SELECT * FROM chapters WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
                (user_id,)
            )
            recent = await cursor.fetchall()
            
            # Task counts
            cursor = await db.execute(
                "SELECT COUNT(*) as count FROM tasks WHERE user_id = ? AND status = 'pending'",
                (user_id,)
            )
            pending = (await cursor.fetchone())["count"]
            
            cursor = await db.execute(
                "SELECT COUNT(*) as count FROM tasks WHERE user_id = ? AND status = 'submitted'",
                (user_id,)
            )
            submitted = (await cursor.fetchone())["count"]
            
            # Get user for display name
            cursor = await db.execute(
                "SELECT display_name FROM users WHERE user_id = ?",
                (user_id,)
            )
            user = await cursor.fetchone()
            
            return {
                "total_earned": row["total"],
                "chapters_count": row["count"],
                "recent_chapters": [dict(r) for r in recent],
                "pending_tasks": pending,
                "submitted_tasks": submitted,
                "display_name": user["display_name"] if user else None
            }
    
    async def get_team_stats(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            
            # Total chapters
            cursor = await db.execute("SELECT COUNT(*) as count FROM chapters")
            total_chapters = (await cursor.fetchone())["count"]
            
            # Total earnings
            cursor = await db.execute("SELECT COALESCE(SUM(price), 0) as total FROM chapters")
            total_earnings = (await cursor.fetchone())["total"]
            
            # Pending tasks
            cursor = await db.execute("SELECT COUNT(*) as count FROM tasks WHERE status = 'pending'")
            pending = (await cursor.fetchone())["count"]
            
            cursor = await db.execute("SELECT COUNT(*) as count FROM tasks WHERE status = 'submitted'")
            submitted = (await cursor.fetchone())["count"]
            
            # Top users
            cursor = await db.execute('''
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
        week_ago = datetime.now(pytz.UTC) - timedelta(days=7)
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute('''
                SELECT user_id, username, display_name, COUNT(*) as chapters, COALESCE(SUM(price), 0) as earnings
                FROM chapters WHERE created_at >= ? GROUP BY user_id ORDER BY chapters DESC
            ''', (week_ago,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
    
    # ========== Logging ==========
    async def log_action(self, action: str, user_id: int, target_id: str = None,
                        details: dict = None, log_type: str = "normal"):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            
            await db.execute(
                '''INSERT INTO logs (action, user_id, target_id, details, timestamp, type)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (action, user_id, target_id, json.dumps(details or {}),
                 datetime.now(pytz.UTC), log_type)
            )
            await db.commit()
    
    async def delete_all_logs(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            
            # Start transaction
            await db.execute("BEGIN")
            
            try:
                # Log the action
                await db.execute(
                    '''INSERT INTO logs (action, user_id, timestamp, type)
                       VALUES (?, ?, ?, ?)''',
                    ("delete_all_logs", user_id, datetime.now(pytz.UTC), "admin")
                )
                
                # Delete non-financial logs
                await db.execute("DELETE FROM logs WHERE type != 'financial'")
                
                await db.commit()
                
            except Exception as e:
                await db.execute("ROLLBACK")
                logger.error(f"Error deleting logs: {e}")

# Create global instance
db = Database()
