#!/usr/bin/env python3
"""
First-time setup: create the database tables and the admin user.

Usage:
    python setup_admin.py                      # interactive prompts
    python setup_admin.py -u admin -p secret   # non-interactive

Running it again for an existing username resets that user's password.
"""
import argparse
import getpass
import sys

from app.database import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/update the ServerHub admin user")
    parser.add_argument("-u", "--username", help="Admin username")
    parser.add_argument("-p", "--password", help="Admin password (omit to be prompted)")
    args = parser.parse_args()

    username = args.username or input("Admin username: ").strip()
    if not username:
        print("Username is required.", file=sys.stderr)
        return 1

    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        return 1

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.hashed_password = hash_password(password)
            user.is_admin = True   # the setup user is always a full admin
            action = "updated"
        else:
            db.add(User(username=username, hashed_password=hash_password(password),
                        is_admin=True, permissions=""))
            action = "created"
        db.commit()
    finally:
        db.close()

    print(f"Admin user '{username}' {action}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
