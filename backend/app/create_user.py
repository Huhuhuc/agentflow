"""Create an initial tenant administrator interactively, without logging credentials."""
import argparse
import getpass
from sqlalchemy import select
from .auth import hash_password
from .database import engine,SessionLocal
from .migrations import upgrade
from .models import Tenant,User


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email",required=True)
    parser.add_argument("--tenant",required=True)
    args=parser.parse_args()
    password=getpass.getpass("Password (at least 12 characters): ")
    if len(password)<12 or password!=getpass.getpass("Repeat password: "):parser.error("Password too short or does not match")
    upgrade(engine)
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email==args.email)):parser.error("Email already exists")
        tenant=Tenant(name=args.tenant);db.add(tenant);db.flush()
        db.add(User(tenant_id=tenant.id,email=args.email,name="Administrator",role="admin",password_hash=hash_password(password)));db.commit()
    print("Administrator created. No credentials were printed.")


if __name__=="__main__":main()
