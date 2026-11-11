import sqlite3
import re

def audit():
    conn = sqlite3.connect('d:/job-agent/jobs.db')
    c = conn.cursor()
    
    c.execute("SELECT id, title, company, url, status, reason, score FROM jobs WHERE status IN ('filled_pending_submit', 'needs_manual_input')")
    rows = c.fetchall()
    
    otp_gated = []
    accenture_sso = []
    static_or_email_cv = []
    no_form_fields = []
    validation_or_other = []
    
    for r in rows:
        j_id, title, company, url, status, reason, score = r
        reason_str = str(reason).lower()
        company_str = str(company).lower()
        url_str = str(url).lower()
        
        if any(kw in reason_str for kw in ['otp', 'sms', 'verification gate']):
            otp_gated.append(r)
        elif 'accenture' in company_str or 'accenture' in url_str or 'myworkday' in url_str:
            accenture_sso.append(r)
        elif any(kw in reason_str for kw in ['no final submit button', 'no fillable form fields']):
            if any(k in url_str for k in ['career', 'vacanc', 'job-search', 'placero', 'billionsunited']):
                static_or_email_cv.append(r)
            else:
                no_form_fields.append(r)
        else:
            validation_or_other.append(r)
            
    print(f"Total Pending/Manual: {len(rows)}")
    print(f"1. Gated by Mobile/SMS/Email OTP (Holding for Phone): {len(otp_gated)}")
    print(f"2. Accenture / External Workday SSO Candidate Portals: {len(accenture_sso)}")
    print(f"3. General Directory / Aggregator / Static Career Pages: {len(static_or_email_cv)}")
    print(f"4. Direct Postings with No Form Fields or Submit Button: {len(no_form_fields)}")
    print(f"5. Form Validation / Specific Dropdown Residuals: {len(validation_or_other)}")

    print("\n--- OTP Gated Sample ---")
    for r in otp_gated[:5]:
        print(f"  [{r[6]}] {r[1]} @ {r[2]} -> {r[5]}")

    print("\n--- Form Validation / Specific Dropdown Residuals ---")
    for r in validation_or_other:
        print(f"  [{r[6]}] {r[1]} @ {r[2]} -> {r[5][:80]}")

if __name__ == '__main__':
    audit()

