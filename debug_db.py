from sqlmodel import Session, select, func
from insti_scraper.core.database import engine
from insti_scraper.domain.models import Professor, University, Department

def check_db():
    with Session(engine) as session:
        prof_count = session.exec(select(func.count(Professor.id))).one()
        dept_count = session.exec(select(func.count(Department.id))).one()
        uni_count = session.exec(select(func.count(University.id))).one()
        
        print(f"Universities: {uni_count}")
        print(f"Departments: {dept_count}")
        print(f"Professors: {prof_count}")
        
        if prof_count > 0:
            profs = session.exec(select(Professor).limit(5)).all()
            for p in profs:
                print(f"- {p.name} ({p.title}) [{p.profile_url}]")

if __name__ == "__main__":
    check_db()
