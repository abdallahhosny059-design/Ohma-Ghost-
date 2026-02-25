import re
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
import logging
from datetime import datetime, timedelta
import pytz
from config import config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self.initialized = False
    
    async def initialize(self):
        if self.initialized:
            return
        
        try:
            self.client = AsyncIOMotorClient(
                config.MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                maxPoolSize=10
            )
            
            await self.client.admin.command('ping')
            
            self.db = self.client[config.DB_NAME]
            
            # Collections
            self.users = self.db['users']
            self.works = self.db['works']
            self.tasks = self.db['tasks']
            self.chapters = self.db['chapters']
            self.logs = self.db['logs']
            
            await self._create_indexes()
            
            self.initialized = True
            logger.info("✅ Database connected")
            
        except Exception as e:
            logger.error(f"❌ Database error: {e}")
            raise
    
    async def _create_indexes(self):
        """Create all indexes"""
        
        # Users
        await self.users.create_index("user_id", unique=True)
        
        # Works
        await self.works.create_index("name", unique=True)
        
        # Tasks - unique per user/work/chapter for non-rejected tasks
        await self.tasks.create_index(
            [("user_id", ASCENDING), ("work", ASCENDING), ("chapter", ASCENDING)],
            unique=True,
            partialFilterExpression={"status": {"$ne": "rejected"}}
        )
        await self.tasks.create_index("status")
        await self.tasks.create_index("created_at")
        
        # Chapters - unique per user/work/chapter
        await self.chapters.create_index(
            [("user_id", ASCENDING), ("work", ASCENDING), ("chapter", ASCENDING)],
            unique=True
        )
        await self.chapters.create_index("created_at")
        
        # Logs - financial logs never expire
        await self.logs.create_index("timestamp")
        await self.logs.create_index("type")
        
        logger.info("✅ Indexes created")
    
    # ========== User Operations ==========
    async def get_or_create_user(self, user_id: str, username: str, display_name: str = None):
        user = await self.users.find_one({"user_id": user_id})
        if not user:
            user = {
                "user_id": user_id,
                "username": username,
                "display_name": display_name or username,
                "joined_at": datetime.now(pytz.UTC),
                "is_banned": False
            }
            await self.users.insert_one(user)
        elif display_name and user.get("display_name") != display_name:
            # Update display name if changed
            await self.users.update_one(
                {"user_id": user_id},
                {"$set": {"display_name": display_name}}
            )
            user["display_name"] = display_name
        return user
    
    # ========== Work Operations ==========
    async def add_work(self, name: str, link: str, added_by: int):
        try:
            await self.works.insert_one({
                "name": name,
                "link": link,
                "added_by": added_by,
                "created_at": datetime.now(pytz.UTC),
                "is_active": True
            })
            
            await self.log_action(
                "add_work",
                added_by,
                details={"name": name, "link": link}
            )
            
            return True, "✅ تمت الإضافة"
        except:
            return False, "❌ العمل موجود مسبقاً"
    
    async def get_work(self, name: str):
        work = await self.works.find_one({
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
            "is_active": True
        })
        return work
    
    async def search_works(self, query: str):
        safe_query = re.escape(query)
        cursor = self.works.find({
            "name": {"$regex": safe_query, "$options": "i"},
            "is_active": True
        }).limit(10)
        return await cursor.to_list(length=10)
    
    async def delete_work(self, name: str, deleted_by: int):
        # Case insensitive delete
        work = await self.works.find_one({
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
            "is_active": True
        })
        
        if not work:
            return False
        
        result = await self.works.update_one(
            {"_id": work["_id"]},
            {"$set": {"is_active": False, "deleted_by": deleted_by}}
        )
        
        if result.modified_count > 0:
            await self.log_action(
                "delete_work",
                deleted_by,
                details={"name": work["name"]}
            )
            return True
        return False
    
    # ========== Task Operations ==========
    async def create_task(self, user_id: str, username: str, display_name: str,
                         work: str, chapter: int, price: int, assigned_by: int):
        try:
            # Validate price
            if price <= 0 or price > config.MAX_PRICE:
                return False, f"❌ السعر يجب أن يكون بين 1 و {config.MAX_PRICE}"
            
            # Validate chapter
            if chapter <= 0:
                return False, "❌ رقم الفصل غير صالح"
            
            # Check if work exists
            work_doc = await self.get_work(work)
            if not work_doc:
                return False, "❌ العمل غير موجود"
            
            # Get or create user
            await self.get_or_create_user(user_id, username, display_name)
            
            await self.tasks.insert_one({
                "user_id": user_id,
                "username": username,
                "display_name": display_name,
                "work": work,
                "chapter": chapter,
                "price": price,
                "status": "pending",
                "assigned_by": assigned_by,
                "created_at": datetime.now(pytz.UTC)
            })
            
            await self.log_action(
                "create_task",
                assigned_by,
                target_id=user_id,
                details={"work": work, "chapter": chapter, "price": price}
            )
            
            return True, "✅ تم التكليف"
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            return False, "❌ هذا الفصل مكلف بالفعل لهذا العضو"
    
    async def get_user_tasks(self, user_id: str, status: str = None):
        query = {"user_id": user_id}
        if status:
            query["status"] = status
        cursor = self.tasks.find(query).sort("created_at", DESCENDING)
        return await cursor.to_list(length=50)
    
    async def submit_task(self, user_id: str, work: str, chapter: int):
        result = await self.tasks.find_one_and_update(
            {
                "user_id": user_id,
                "work": work,
                "chapter": chapter,
                "status": "pending"
            },
            {
                "$set": {
                    "status": "submitted",
                    "submitted_at": datetime.now(pytz.UTC)
                }
            },
            return_document=True
        )
        
        # Single source of truth for logging
        await self.log_action(
            "submit_task",
            int(user_id),
            details={
                "work": work, 
                "chapter": chapter, 
                "success": result is not None
            },
            log_type="normal"
        )
        
        return result
    
    async def approve_task(self, user_id: str, work: str, chapter: int, approved_by: int):
        async with await self.client.start_session() as session:
            async with session.start_transaction():
                
                # Check if user exists
                user = await self.users.find_one({"user_id": user_id}, session=session)
                if not user:
                    await session.abort_transaction()
                    return None
                
                # Update task with strict conditions to prevent race condition
                task = await self.tasks.find_one_and_update(
                    {
                        "user_id": user_id,
                        "work": work,
                        "chapter": chapter,
                        "status": "submitted",
                        "approved_at": {"$exists": False}  # Ensure not already approved
                    },
                    {
                        "$set": {
                            "status": "approved",
                            "approved_by": approved_by,
                            "approved_at": datetime.now(pytz.UTC)
                        }
                    },
                    session=session,
                    return_document=True
                )
                
                if not task:
                    await session.abort_transaction()
                    return None
                
                # Create chapter record
                try:
                    await self.chapters.insert_one({
                        "user_id": user_id,
                        "username": task["username"],
                        "display_name": task.get("display_name", task["username"]),
                        "work": work,
                        "chapter": chapter,
                        "price": task["price"],
                        "approved_by": approved_by,
                        "created_at": datetime.now(pytz.UTC)
                    }, session=session)
                except:
                    await session.abort_transaction()
                    return None
                
                # Log financial transaction
                await self.log_action(
                    "financial_approve",
                    approved_by,
                    target_id=user_id,
                    details={
                        "work": work,
                        "chapter": chapter,
                        "price": task["price"]
                    },
                    log_type="financial",
                    session=session
                )
                
                return task
    
    async def reject_task(self, user_id: str, work: str, chapter: int, 
                         rejected_by: int, reason: str):
        result = await self.tasks.find_one_and_update(
            {
                "user_id": user_id,
                "work": work,
                "chapter": chapter,
                "status": "submitted"
            },
            {
                "$set": {
                    "status": "rejected",
                    "rejected_by": rejected_by,
                    "reject_reason": reason,
                    "rejected_at": datetime.now(pytz.UTC)
                }
            },
            return_document=True
        )
        
        if result:
            await self.log_action(
                "reject_task",
                rejected_by,
                target_id=user_id,
                details={"work": work, "chapter": chapter, "reason": reason}
            )
        
        return result
    
    # ========== Stats Operations ==========
    async def get_user_stats(self, user_id: str):
        # Get total via aggregation
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$group": {
                "_id": None,
                "total_earned": {"$sum": "$price"},
                "chapters_count": {"$sum": 1}
            }}
        ]
        result = await self.chapters.aggregate(pipeline).to_list(length=1)
        
        if result:
            total_earned = result[0]["total_earned"]
            chapters_count = result[0]["chapters_count"]
        else:
            total_earned = 0
            chapters_count = 0
        
        # Get recent chapters
        recent = await self.chapters.find(
            {"user_id": user_id}
        ).sort("created_at", DESCENDING).limit(10).to_list(length=10)
        
        # Get pending/submitted tasks
        pending = await self.tasks.count_documents({
            "user_id": user_id,
            "status": "pending"
        })
        submitted = await self.tasks.count_documents({
            "user_id": user_id,
            "status": "submitted"
        })
        
        # Get user info for display name
        user = await self.users.find_one({"user_id": user_id})
        display_name = user.get("display_name") if user else None
        
        return {
            "total_earned": total_earned,
            "chapters_count": chapters_count,
            "recent_chapters": recent,
            "pending_tasks": pending,
            "submitted_tasks": submitted,
            "display_name": display_name
        }
    
    async def get_team_stats(self):
        # Total chapters
        total_chapters = await self.chapters.count_documents({})
        
        # Total earnings
        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$price"}}}]
        result = await self.chapters.aggregate(pipeline).to_list(length=1)
        total_earnings = result[0]["total"] if result else 0
        
        # Tasks stats
        pending = await self.tasks.count_documents({"status": "pending"})
        submitted = await self.tasks.count_documents({"status": "submitted"})
        
        # Top users
        top_pipeline = [
            {"$group": {
                "_id": "$user_id",
                "count": {"$sum": 1},
                "total": {"$sum": "$price"}
            }},
            {"$sort": {"count": -1}},
            {"$limit": 5}
        ]
        top_users = await self.chapters.aggregate(top_pipeline).to_list(length=5)
        
        # Get display names for top users
        for user in top_users:
            user_doc = await self.users.find_one({"user_id": user["_id"]})
            user["display_name"] = user_doc.get("display_name") if user_doc else "Unknown"
        
        return {
            "total_chapters": total_chapters,
            "total_earnings": total_earnings,
            "pending_tasks": pending,
            "submitted_tasks": submitted,
            "top_users": top_users
        }
    
    async def get_weekly_report(self):
        week_ago = datetime.now(pytz.UTC) - timedelta(days=7)
        
        pipeline = [
            {"$match": {"created_at": {"$gte": week_ago}}},
            {"$group": {
                "_id": "$user_id",
                "chapters": {"$sum": 1},
                "earnings": {"$sum": "$price"}
            }},
            {"$sort": {"chapters": -1}}
        ]
        
        result = await self.chapters.aggregate(pipeline).to_list(length=20)
        
        # Get display names
        for item in result:
            user_doc = await self.users.find_one({"user_id": item["_id"]})
            item["display_name"] = user_doc.get("display_name") if user_doc else "Unknown"
        
        return result
    
    # ========== Logging with Transaction for delete_all_logs ==========
    async def log_action(self, action: str, user_id: int, target_id: str = None,
                        details: dict = None, log_type: str = "normal", session=None):
        log = {
            "action": action,
            "user_id": user_id,
            "target_id": target_id,
            "details": details or {},
            "timestamp": datetime.now(pytz.UTC),
            "type": log_type
        }
        
        if session:
            await self.logs.insert_one(log, session=session)
        else:
            await self.logs.insert_one(log)
    
    async def delete_all_logs(self, user_id: int):
        """Only owner can delete logs - with transaction"""
        async with await self.client.start_session() as session:
            async with session.start_transaction():
                
                # Create log entry first
                log_entry = {
                    "action": "delete_all_logs",
                    "user_id": user_id,
                    "timestamp": datetime.now(pytz.UTC),
                    "type": "admin"
                }
                
                # Insert it
                result = await self.logs.insert_one(log_entry, session=session)
                
                # Delete everything except this log and financial logs
                await self.logs.delete_many({
                    "_id": {"$ne": result.inserted_id},
                    "type": {"$ne": "financial"}
                }, session=session)

# Create global instance
db = Database()