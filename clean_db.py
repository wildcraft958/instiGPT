from sqlmodel import Session
from insti_scraper.core.database import engine
from sqlalchemy import text

def clean():
    with Session(engine) as session:
        session.exec(text("DELETE FROM professor"))
        session.exec(text("DELETE FROM department"))
        session.exec(text("DELETE FROM university"))
        session.commit()
        print("Done")

if __name__ == "__main__":
    clean()
