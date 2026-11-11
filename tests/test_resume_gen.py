import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from app.config import load_config
from app.profile_loader import load_profile
from app.resume_tailorer import ResumeTailorer
from app.utils import JobPosting

def test_resume_generation():
    config = load_config()
    tailorer = ResumeTailorer(config.project_root)
    job_py = JobPosting(url="test1", source="linkedin", company="Zerodha", title="Python Backend Engineer", description="Python, FastAPI, Redis, WebSockets")
    job_vapt = JobPosting(url="test2", source="naukri", company="Palo Alto", title="VAPT Analyst", description="Burp Suite, OWASP, Penetration Testing")
    prof = load_profile(config.profile_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        pdf_py = tailorer.generate_tailored_pdf(job_py, prof, page)
        print("Python PDF:", pdf_py, "Size:", Path(pdf_py).stat().st_size)

        pdf_vapt = tailorer.generate_tailored_pdf(job_vapt, prof, page)
        print("VAPT PDF:", pdf_vapt, "Size:", Path(pdf_vapt).stat().st_size)

        context.close()
        browser.close()

if __name__ == "__main__":
    test_resume_generation()
