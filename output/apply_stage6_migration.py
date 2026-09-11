from dotenv import load_dotenv
load_dotenv()
from talent_portal.migrations import init_recruitment_db
init_recruitment_db()
print("stage6_migration=complete")
