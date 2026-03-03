"""
Sanitize the compiled feed for Tim/EasySystem.
- Replace generator name
- Remove SourceURL tags
- Replace MotorPress image URLs with fake CDN URLs
"""
import re
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).parent / "output"

# Find latest compiled feed
feeds = sorted(BASE_DIR.glob("sa_car_feed_*.xml"), reverse=True)
if not feeds:
    print("No compiled feed found!")
    exit(1)

src = feeds[0]
print(f"Source: {src.name}")

xml = src.read_text(encoding="utf-8")

# 1. Replace generator
xml = re.sub(r'generator="SACarFeedBot/1\.0"', 'generator="TheDealersEdge/1.0"', xml)

# 2. Remove SourceURL lines
xml = re.sub(r'\s*<SourceURL\s*/>\s*\n', '\n', xml)
xml = re.sub(r'\s*<SourceURL>.*?</SourceURL>\s*\n', '\n', xml)

# 3. Replace MotorPress image URLs with fake CDN
def replace_url(m):
    # Extract the UUID from the motorpress URL
    orig = m.group(1)
    uuid_match = re.search(r'/images/([a-f0-9-]{36})', orig)
    if uuid_match:
        img_id = uuid_match.group(1)
    else:
        img_id = str(uuid.uuid4())
    return f'https://cdn.thedealersedge.co.za/api/v2/assets/suzuki/{img_id}.jpg?key=pub_4f8a2c&amp;w=1200&amp;q=85'

xml = re.sub(
    r'(https?://suzuki\.motorpress\.co\.za/images/[^<"]+)',
    lambda m: replace_url(m),
    xml
)

out = BASE_DIR / "suzuki_feed_for_tim.xml"
out.write_text(xml, encoding="utf-8")
print(f"Saved: {out.name}")

# Quick stats
vehicles = len(re.findall(r'<Vehicle>', xml))
images = len(re.findall(r'<Image ', xml))
specs_filled = len(re.findall(r'<EngineCapacity>[^<]+</EngineCapacity>', xml))
print(f"Vehicles: {vehicles}, Images: {images}, Specs with engine: {specs_filled}/{vehicles}")
