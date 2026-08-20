import time
import requests
import urllib.parse
import gc
import re
import random
import os
import json
import sys
import base64
import traceback
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# --- STRICT ENVIRONMENT VARIABLES (No Hardcoded Secrets) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("[-] Error: BOT_TOKEN is missing from environment variables!")
    sys.exit(1)

TARGET_CHATS_RAW = os.getenv("TARGET_CHATS")
if not TARGET_CHATS_RAW:
    print("[-] Error: TARGET_CHATS is missing from environment variables!")
    sys.exit(1)
TARGET_CHATS = [c.strip() for c in TARGET_CHATS_RAW.split(",") if c.strip()]

API_ENDPOINT = os.getenv("API_ENDPOINT")
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
ADMITAD_BASE_LINK = os.getenv("ADMITAD_BASE_LINK")

# --- GITHUB DUP-CHECK CONFIGURATION ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
GITHUB_FILE_PATH = os.getenv("GITHUB_FILE_PATH", "sent_products.txt")

if GITHUB_TOKEN and REPO_OWNER and REPO_NAME:
    GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{GITHUB_FILE_PATH}"
    GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{GITHUB_FILE_PATH}"
    GITHUB_HEADERS = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
else:
    GITHUB_API_URL = ""
    GITHUB_RAW_URL = ""
    GITHUB_HEADERS = {}
    print("[!] GitHub variables missing. Running in local-only mode.")

SENT_FILE_LOCAL = "sent_products.txt"
POST_INTERVAL_SECONDS = int(os.getenv("POST_INTERVAL", 1200))  # 20 Minutes default

CATEGORY_URLS = [
    "https://www.shopsy.in/mens-clothing-online",
    "https://www.shopsy.in/footwear-online",
    "https://www.shopsy.in/mens-jeans-online",
    "https://www.shopsy.in/tshirt-for-men-online",
    "https://www.shopsy.in/co-ord-sets-for-men-online",
    "https://www.shopsy.in/mens-topwear-online",
    "https://www.shopsy.in/suits-for-men-online",
    "https://www.shopsy.in/",
    "https://www.shopsy.in/search?q=airpods",
    "https://www.shopsy.in/search?q=laptop",
    "https://www.shopsy.in/search?q=desktop"
]

def load_sent_ids_from_github():
    """Reads sent product IDs from GitHub sent_products.txt file."""
    sent_set = set()
    
    if os.path.exists(SENT_FILE_LOCAL):
        try:
            with open(SENT_FILE_LOCAL, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        sent_set.add(line.strip())
        except Exception as e:
            print(f"[-] Local file read warning: {e}")

    if GITHUB_TOKEN:
        try:
            res = requests.get(GITHUB_RAW_URL, headers=GITHUB_HEADERS, timeout=15)
            if res.status_code == 200:
                remote_ids = set(line.strip() for line in res.text.splitlines() if line.strip())
                sent_set.update(remote_ids)
                print(f"[+] Synced {len(remote_ids)} IDs from GitHub ({GITHUB_FILE_PATH}).")
            elif res.status_code == 404:
                print(f"[!] GitHub file {GITHUB_FILE_PATH} not found. Will be created on first post.")
            else:
                print(f"[-] GitHub fetch returned status code: {res.status_code}")
        except Exception as e:
            print(f"[-] GitHub fetch error: {e}")

    return sent_set

def save_sent_id_to_github(pid, current_set):
    """Appends PID locally and syncs updated text file to GitHub repo."""
    current_set.add(pid)
    
    try:
        with open(SENT_FILE_LOCAL, "a", encoding="utf-8") as f:
            f.write(f"{pid}\n")
    except Exception as e:
        print(f"[-] Local save error: {e}")

    if not GITHUB_TOKEN:
        return False

    try:
        sha = None
        get_res = requests.get(GITHUB_API_URL, headers=GITHUB_HEADERS, timeout=15)
        if get_res.status_code == 200:
            sha = get_res.json().get("sha")

        file_content = "\n".join(sorted(list(current_set))) + "\n"
        encoded_content = base64.b64encode(file_content.encode("utf-8")).decode("utf-8")

        payload = {
            "message": f"Auto-add sent product ID: {pid}",
            "content": encoded_content
        }
        if sha:
            payload["sha"] = sha

        put_res = requests.put(GITHUB_API_URL, headers=GITHUB_HEADERS, json=payload, timeout=20)
        if put_res.status_code in [200, 201]:
            print(f"[+] GitHub Sync Success! Saved product ID {pid} to GitHub.")
            return True
        else:
            print(f"[-] GitHub update failed ({put_res.status_code}): {put_res.text[:100]}")
    except Exception as e:
        print(f"[-] GitHub Sync Error: {e}")
        
    return False

def get_optimized_driver():
    """Starts a headless Chrome browser optimized for Docker & memory stability."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-zygote")
    chrome_options.add_argument("--disable-site-isolation-trials")
    chrome_options.add_argument("--js-flags=--max-old-space-size=256")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheet": 2,
        "profile.managed_default_content_settings.fonts": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)

    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
    driver.set_page_load_timeout(30)
    return driver

def create_admitad_deeplink(shopsy_url):
    if not ADMITAD_BASE_LINK:
        return shopsy_url
    encoded_url = urllib.parse.quote_plus(shopsy_url)
    return f"{ADMITAD_BASE_LINK}?ulp={encoded_url}"

def extract_pid_from_url(url):
    match = re.search(r'/(itm[a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

def extract_product_details(soup):
    specs_text = ""
    specs_containers = soup.find_all('div', {'class': '_2418kt'}) 
    if specs_containers:
        for block in specs_containers:
            specs_text += block.get_text(separator='. ') + "\n"
    
    key_specs = soup.find_all('li', {'class': '_21Ahn-'})
    features_list = []
    for li in key_specs:
        features_list.append(li.get_text(strip=True))
        specs_text += li.get_text(strip=True) + "\n"
        
    if len(specs_text) < 50:
        specs_text = soup.get_text(separator=' ')

    images = []
    img_tags = soup.find_all('img', {'class': '_396cs4'}) 
    
    for img in img_tags:
        src = img.get('src')
        if src:
            hq_src = src.replace('/128/128/', '/832/832/')
            if hq_src not in images:
                images.append(hq_src)
    
    if not images:
        all_imgs = soup.find_all('img')
        for img in all_imgs:
            src = img.get('src')
            if src and 'rukminim' in src: 
                hq_src = src.replace('/128/128/', '/832/832/')
                images.append(hq_src)

    images_str = ",".join(images[:4])
    return specs_text, features_list, images_str

def send_to_website_api(deal):
    if not API_ENDPOINT or not API_SECRET_KEY:
        print("⚠️ Skipped Website API: API_ENDPOINT or SECRET_KEY missing from ENV")
        return
        
    print("🤖 Sending to Website API...")
    payload = {
        'api_key': API_SECRET_KEY,
        'title': deal['title'],
        'information': deal['ai_context'],
        'affiliate_link': deal['link'],
        'images': deal['images'], 
        'price': deal['price'],   
        'mrp': deal['mrp'],       
        'discount': deal['discount'] 
    }
    try:
        res = requests.post(API_ENDPOINT, data=payload, timeout=60) 
        if res.status_code == 200:
            print("✅ API Success: Saved to DB & AI Started")
        else:
            print(f"❌ API Failed ({res.status_code}): {res.text[:100]}")
    except Exception as e:
        print(f"❌ Connection Error to Website API: {e}")

def send_telegram_alert(deal):
    feature_text = ""
    if deal['features']:
        for f in deal['features'][:3]:
            feature_text += f"▪️ {f}\n"
            
    image_urls = []
    if deal['images']:
        image_urls = [i.strip() for i in deal['images'].split(',') if i.strip()]
    
    msg = (
        f"🚨 *LOOT ALERT: {deal['discount']}% OFF* 🚨\n\n"
        f"📦 *{deal['title']}*\n\n"
        f"💸 *Offer Price:* ₹{deal['price']}  ~₹{deal['mrp']}~\n\n"
        f"⚙️ *Key Features:*\n{feature_text}\n"
        f"🛒 *BUY NOW (Loot Link):*\n{deal['link']}\n\n"
        f"⚡ _Fast! Stock is limited._"
    )
    
    for chat_id in TARGET_CHATS:
        try:
            if len(image_urls) > 1:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
                media_group = []
                for i, img_url in enumerate(image_urls):
                    media_item = {"type": "photo", "media": img_url}
                    if i == 0:
                        media_item["caption"] = msg
                        media_item["parse_mode"] = "Markdown"
                    media_group.append(media_item)
                payload = {"chat_id": chat_id, "media": json.dumps(media_group)}
                requests.post(url, data=payload, timeout=20)
                
            elif len(image_urls) == 1:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                payload = {"chat_id": chat_id, "photo": image_urls[0], "caption": msg, "parse_mode": "Markdown"}
                requests.post(url, data=payload, timeout=15)
                
            else:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": False}
                requests.post(url, data=payload, timeout=15)
                
            print(f"📢 Telegram Sent to {chat_id}")
        except Exception as e:
            print(f"⚠️ Telegram Error for {chat_id}: {e}")

def fetch_deals_and_process(active_urls):
    sent_ids = load_sent_ids_from_github()
    print(f"[Info] Total loaded history IDs: {len(sent_ids)}")

    current_categories = active_urls.copy()
    random.shuffle(current_categories)

    for cat_url in current_categories:
        cat_name = urllib.parse.unquote(cat_url.split("/")[-1]).replace("-", " ").replace("search?q=", "Search: ").title()
        if not cat_name: 
            cat_name = "Category"
        
        print(f"\n🚀 Scanning Category: {cat_name}")
        
        products_processed = 0
        category_deals = []
        driver = None

        try:
            driver = get_optimized_driver()
            
            # 3 pages tak check karenge taaki 10 unique unseen products mil sakein
            for page_num in range(1, 4):
                if products_processed >= 10:
                    break # 10 products pure hone par loop break karein

                print(f"[*] Page {page_num}...")
                paged_url = f"{cat_url}&page={page_num}" if "?" in cat_url else f"{cat_url}?page={page_num}"
                driver.get(paged_url)
                time.sleep(4)
                
                page_source = driver.page_source
                pattern = r'(/[a-zA-Z0-9\-]+/p/itm[a-zA-Z0-9]+)'
                raw_links = list(set(re.findall(pattern, page_source)))
                
                print(f"[+] Found {len(raw_links)} product candidates on Page {page_num}.")

                for partial_link in raw_links:
                    if products_processed >= 10:
                        break # Yahan bhi limit check karein taaki 10 ke baad process na ho

                    try:
                        pid = extract_pid_from_url(partial_link)
                        if pid and pid in sent_ids:
                            continue

                        full_url = "https://www.shopsy.in" + partial_link
                        title = partial_link.split('/')[1].replace('-', ' ').title()
                        
                        driver.get(full_url)
                        time.sleep(2)
                        
                        products_processed += 1 # Product process count badhayein
                        print(f"   [{products_processed}/10] Checking: {title[:25]}...")
                        
                        soup = BeautifulSoup(driver.page_source, 'html.parser')
                        body_text = soup.get_text(separator=' ')
                        
                        prices_found = re.findall(r'₹([0-9,]+)', body_text)
                        if not prices_found: 
                            continue
                        
                        clean_prices = [float(p.replace(',', '')) for p in prices_found]
                        selling_price = clean_prices[0]
                        original_price = 0.0
                        
                        for p in clean_prices:
                            if p > selling_price:
                                original_price = p
                                break
                        
                        discount_val = 0
                        discount_match = re.search(r'([0-9]+)%\s*off', body_text, re.IGNORECASE)
                        if discount_match:
                            discount_val = int(discount_match.group(1))
                        elif original_price > selling_price:
                            discount_val = int(((original_price - selling_price) / original_price) * 100)
                        
                        if original_price == 0 and discount_val > 0:
                            original_price = int(selling_price * 100 / (100 - discount_val))
                        
                        if original_price == 0:
                            original_price = selling_price

                        if discount_val >= 50:
                            full_details, features, images_str = extract_product_details(soup)
                            ai_context = (
                                f"Product Name: {title}\n"
                                f"Current Price: {selling_price}\n"
                                f"MRP: {original_price}\n"
                                f"Discount: {discount_val}%\n"
                                f"Key Features: {', '.join(features[:5])}\n"
                                f"Full Specifications: {full_details[:2000]}"
                            )
                            earning_link = create_admitad_deeplink(full_url)
                            
                            deal_data = {
                                'title': title,
                                'price': selling_price,
                                'mrp': original_price,
                                'discount': discount_val,
                                'features': features,
                                'link': earning_link,
                                'ai_context': ai_context,
                                'images': images_str
                            }
                            category_deals.append({'deal': deal_data, 'pid': pid})
                            print(f"      -> Valid Deal Added: ₹{selling_price} | {discount_val}% OFF")
                            
                    except Exception as item_err:
                        continue
            
            # Jab 10 products process ho jayein (ya deals mil jayein), tab sabse best select karein
            if category_deals:
                category_deals.sort(key=lambda x: x['deal']['price'])
                best_item = category_deals[0]
                best_deal = best_item['deal']
                best_pid = best_item['pid']
                
                print(f"\n🌟 Selected Best Deal from Category: {best_deal['title'][:30]} @ ₹{best_deal['price']}")
                
                send_to_website_api(best_deal)
                send_telegram_alert(best_deal) 
                
                if best_pid:
                    save_sent_id_to_github(best_pid, sent_ids)

                print(f"\n⏳ Posted successfully! Category rotating in {POST_INTERVAL_SECONDS} seconds...")
                time.sleep(POST_INTERVAL_SECONDS)
            else:
                print(f"\n[-] No valid deals (>50% off) found in the {products_processed} products checked. Switching Category...")
                time.sleep(5) # Agar koi deal nahi mili toh immediately next category par jayein
                    
        except Exception as e:
            print(f"[!] Scraper Category Error: {e}")
        finally:
            if driver:
                try: driver.quit()
                except: pass
            gc.collect()

def main():
    print("=" * 60)
    print("🚀 Shopsy Deal Bot (Strict Environment Mode)")
    print("=" * 60)

    user_search = os.getenv("SEARCH_KEYWORDS", "").strip()
    
    if not user_search and sys.stdin.isatty():
        try:
            user_search = input("🔍 Enter custom keywords (comma separated) or press ENTER for default: ").strip()
        except (EOFError, KeyboardInterrupt):
            user_search = ""

    active_urls = []
    if user_search:
        keywords = [k.strip() for k in user_search.split(',')]
        for kw in keywords:
            if kw:
                encoded_kw = urllib.parse.quote_plus(kw)
                active_urls.append(f"https://www.shopsy.in/search?q={encoded_kw}")
        print(f"🎯 Custom Keywords Active: {user_search}")
    else:
        active_urls = CATEGORY_URLS.copy()
        print("🎯 Default Mode Active: Scanning all main categories.")

    while True:
        try:
            fetch_deals_and_process(active_urls)
            print(f"\n💤 Scanning cycle completed. Resting for {POST_INTERVAL_SECONDS} seconds...")
            time.sleep(POST_INTERVAL_SECONDS)
        except Exception as crash_err:
            print(f"\n[!] Unexpected Error trapped (Anti-Crash active): {crash_err}")
            traceback.print_exc()
            print("[!] Restarting cycle in 30 seconds...")
            time.sleep(30)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Bot stopped manually.")
        sys.exit(0)
