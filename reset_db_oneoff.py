import asyncio
from arch_fingerprint.db.session import engine
from arch_fingerprint.db.models import Base

async def reset_db():
    try:
        async with engine.begin() as conn:
            print("Dropping all tables...")
            await conn.run_sync(Base.metadata.drop_all)
            print("Creating all tables...")
            await conn.run_sync(Base.metadata.create_all)
        print("✅ Database reset successfully.")
    except Exception as e:
        print(f"❌ Database reset failed: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(reset_db())
