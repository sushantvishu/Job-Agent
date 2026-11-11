import urllib.parse

naukri_keywords = ['vapt', 'penetration tester', 'application security']
linkedin_keywords = ['VAPT Analyst', 'Application Security']

naukri_exps = ['0', '0%2C1', '1']
linkedin_exps = ['1', '2', '1%2C2']

n_urls = []
for k in naukri_keywords:
    k_encoded = k.replace(' ', '+')
    k_dash = k.replace(' ', '-')
    for e in naukri_exps:
        n_urls.append(f"https://www.naukri.com/{k_dash}-jobs-in-india?k={k_encoded}&l=india&experience={e}")

l_urls = []
for k in linkedin_keywords:
    k_encoded = urllib.parse.quote(k)
    for e in linkedin_exps:
        l_urls.append(f"https://www.linkedin.com/jobs/search/?keywords={k_encoded}&location=India&f_E={e}")

with open('jobs/naukri_urls.txt', 'w') as f:
    f.write('\n'.join(n_urls))

with open('jobs/linkedin_urls.txt', 'w') as f:
    f.write('\n'.join(l_urls))

