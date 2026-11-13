"""
Create the Project Health Checker tables in the PostgreSQL database
configured via DATABASE_URL (server/.env).

Usage:
    cd server
    python init_db.py
"""
import sys

import db


def main() -> int:
    if not db.is_configured():
        print("DATABASE_URL is not set. Add it to server/.env first (see .env.example).")
        return 1

    print("Connecting...")
    if not db.check_connection():
        print("Could not connect to the database. Check DATABASE_URL and that PostgreSQL is reachable.")
        return 1

    print("Connected. Applying schema.sql...")
    db.init_schema()
    print("Done — tables created (or already existed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
