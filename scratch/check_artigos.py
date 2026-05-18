import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

def check_artigos():
    print(f"Checking 'artigos' table...")
    try:
        r = httpx.get(f"{SUPABASE_URL}/rest/v1/artigos?select=*&limit=1", headers=headers)
        if r.status_code == 200:
            data = r.json()
            if data:
                print("Columns in 'artigos':", list(data[0].keys()))
                # Check if it has structure or just text
                print("Sample text:", data[0].get("texto")[:100] if data[0].get("texto") else "None")
            else:
                print("'artigos' table is empty.")
        else:
            print(f"Error: {r.text}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    check_artigos()
