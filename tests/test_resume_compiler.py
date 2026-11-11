from pathlib import Path
from app.profile_loader import load_profile
from app.resume_compiler import DynamicResumeCompiler


def test_resume_compiler_context():
    prof = load_profile("vapt")
    compiler = DynamicResumeCompiler()
    ctx = compiler.build_context(prof, "VAPT Analyst", "CyberSecurity Inc", "VAPT and Burp Suite")
    assert ctx["name"] == prof.name
    assert "CyberSecurity Inc" in ctx["summary"]
    assert "VAPT" in ctx["security_skills"]
    assert "Python" in ctx["dev_skills"]


def test_resume_compiler_generates_pdf(tmp_path: Path):
    prof = load_profile("vapt")
    compiler = DynamicResumeCompiler()
    compiler.exports_dir = tmp_path
    pdf = compiler.compile_tailored_pdf(
        prof,
        "VAPT Analyst",
        "Test Security Corp",
        "OWASP, Burp Suite, Network Pentesting",
        filename_prefix="test_ats_resume",
    )
    assert pdf.exists()
    assert pdf.stat().st_size > 1000  # Valid non-empty PDF
