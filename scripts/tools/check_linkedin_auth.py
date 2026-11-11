from playwright.sync_api import sync_playwright

def check_linkedin():
    with sync_playwright() as p:
        print("Launching persistent context...")
        context = p.chromium.launch_persistent_context(
            user_data_dir="d:/job-agent/browser-profile",
            headless=True,
            channel="chrome"
        )
        page = context.new_page()
        print("Navigating to LinkedIn...")
        page.goto("https://www.linkedin.com/feed/", timeout=15000)
        page.wait_for_timeout(3000)
        
        url = page.url
        print(f"Current URL: {url}")
        if "login" in url or "signup" in url or "authwall" in url:
            print("STATUS: NOT LOGGED IN")
        else:
            print("STATUS: LOGGED IN")
            
        context.close()

if __name__ == "__main__":
    check_linkedin()
