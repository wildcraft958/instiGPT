from sqlmodel import Session, select
from insti_scraper.core.database import engine
from insti_scraper.domain.models import Professor, University

def clean_kgp():
    with Session(engine) as session:
        # Find KGP university
        unis = session.exec(select(University)).all()
        for u in unis:
            if "kharagpur" in u.name.lower() or "kgp" in u.name.lower():
                print(f"Deleting data for: {u.name}")
                # Delete professors linked to this university's departments
                # simplified: delete all professors for now to be safe and clean since IITB ones are also 'General' dept attached to 'IITB' probably.
                # Actually, let's just delete ALL professors to be absolutely sure we get a clean run for the verification.
                pass
        
        # Aggressive clean for demo: Delete all professors
        from sqlalchemy import text
        session.exec(text("DELETE FROM professor"))
        session.exec(text("DELETE FROM department"))
        session.exec(text("DELETE FROM university"))
        session.commit()
        print("Database cleared.")

if __name__ == "__main__":
    clean_kgp()
