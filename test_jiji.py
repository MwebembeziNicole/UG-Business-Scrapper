from scrapers.jiji import _pw_scrape_listing, _map_category

url = "https://jiji.ug/arua/clothing/original-kitenge-nJF0cI9Qz0nTVr0sl30ahAEY.html?page=1&pos=12&cur_pos=12&ads_per_page=18&ads_count=475&lid=uFoaGWO9Q9XsiiUP&indexPosition=11"

print("Scraping listing...")
data = _pw_scrape_listing(url)

print("Seller name :", data.get('seller_name', '—'))
print("Phones      :", data.get('phones', []))
print("Location    :", data.get('location', '—'))
print("Category    :", _map_category(data.get('breadcrumb', '') + ' ' + url))
