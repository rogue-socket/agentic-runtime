CATEGORIES = [
    {"id": 1, "name": "Electronics", "slug": "electronics"},
    {"id": 2, "name": "Clothing", "slug": "clothing"},
    {"id": 3, "name": "Home & Kitchen", "slug": "home-kitchen"},
    {"id": 4, "name": "Books", "slug": "books"},
    {"id": 5, "name": "Sports & Outdoors", "slug": "sports-outdoors"},
]

PRODUCTS = [
    # Electronics
    {"id": 1, "name": "Wireless Bluetooth Headphones", "price": 59.99, "category_id": 1, "brand": "SoundMax", "rating": 4.5, "stock": 120, "description": "Noise-cancelling over-ear headphones with 30h battery life."},
    {"id": 2, "name": "USB-C Fast Charger", "price": 24.99, "category_id": 1, "brand": "ChargeTech", "rating": 4.2, "stock": 300, "description": "65W GaN charger with dual USB-C ports."},
    {"id": 3, "name": "Mechanical Keyboard", "price": 89.99, "category_id": 1, "brand": "KeyMaster", "rating": 4.7, "stock": 75, "description": "RGB backlit mechanical keyboard with Cherry MX switches."},
    {"id": 4, "name": "4K Webcam", "price": 119.99, "category_id": 1, "brand": "VisionPro", "rating": 4.3, "stock": 50, "description": "Ultra HD webcam with auto-focus and built-in mic."},
    {"id": 5, "name": "Portable SSD 1TB", "price": 79.99, "category_id": 1, "brand": "DataVault", "rating": 4.8, "stock": 200, "description": "Compact external SSD with USB 3.2 speeds up to 1050MB/s."},

    # Clothing
    {"id": 6, "name": "Classic Fit Cotton T-Shirt", "price": 19.99, "category_id": 2, "brand": "BasicWear", "rating": 4.1, "stock": 500, "description": "Soft 100% cotton crew-neck tee available in multiple colors."},
    {"id": 7, "name": "Slim Fit Jeans", "price": 49.99, "category_id": 2, "brand": "DenimCo", "rating": 4.4, "stock": 180, "description": "Stretch denim jeans with a modern slim fit."},
    {"id": 8, "name": "Running Sneakers", "price": 74.99, "category_id": 2, "brand": "StrideFlex", "rating": 4.6, "stock": 90, "description": "Lightweight mesh sneakers with responsive cushioning."},
    {"id": 9, "name": "Waterproof Jacket", "price": 129.99, "category_id": 2, "brand": "TrailGuard", "rating": 4.5, "stock": 60, "description": "Breathable waterproof shell jacket for all-weather use."},
    {"id": 10, "name": "Wool Beanie", "price": 14.99, "category_id": 2, "brand": "CozyKnit", "rating": 4.0, "stock": 400, "description": "Warm merino wool beanie with a ribbed knit design."},

    # Home & Kitchen
    {"id": 11, "name": "Stainless Steel Water Bottle", "price": 22.99, "category_id": 3, "brand": "HydroLife", "rating": 4.6, "stock": 350, "description": "Double-wall insulated bottle that keeps drinks cold for 24h."},
    {"id": 12, "name": "Non-Stick Frying Pan", "price": 34.99, "category_id": 3, "brand": "ChefPro", "rating": 4.3, "stock": 150, "description": "12-inch ceramic-coated pan with ergonomic handle."},
    {"id": 13, "name": "LED Desk Lamp", "price": 39.99, "category_id": 3, "brand": "BrightSpace", "rating": 4.4, "stock": 110, "description": "Adjustable LED lamp with 5 brightness levels and USB charging port."},
    {"id": 14, "name": "Electric Kettle", "price": 29.99, "category_id": 3, "brand": "BrewQuick", "rating": 4.2, "stock": 200, "description": "1.7L stainless steel kettle with rapid boil technology."},
    {"id": 15, "name": "Bamboo Cutting Board Set", "price": 18.99, "category_id": 3, "brand": "NaturaCut", "rating": 4.5, "stock": 250, "description": "Set of 3 organic bamboo cutting boards in different sizes."},

    # Books
    {"id": 16, "name": "Python Crash Course", "price": 35.99, "category_id": 4, "brand": "NoStarch Press", "rating": 4.7, "stock": 100, "description": "A hands-on, project-based introduction to programming with Python."},
    {"id": 17, "name": "Clean Code", "price": 39.99, "category_id": 4, "brand": "Prentice Hall", "rating": 4.6, "stock": 85, "description": "A handbook of agile software craftsmanship by Robert C. Martin."},
    {"id": 18, "name": "The Great Gatsby", "price": 12.99, "category_id": 4, "brand": "Scribner", "rating": 4.4, "stock": 300, "description": "F. Scott Fitzgerald's classic novel of the Jazz Age."},
    {"id": 19, "name": "Atomic Habits", "price": 16.99, "category_id": 4, "brand": "Avery", "rating": 4.8, "stock": 220, "description": "Tiny changes, remarkable results — build good habits and break bad ones."},
    {"id": 20, "name": "Dune", "price": 14.99, "category_id": 4, "brand": "Ace Books", "rating": 4.7, "stock": 170, "description": "Frank Herbert's epic science fiction masterpiece."},

    # Sports & Outdoors
    {"id": 21, "name": "Yoga Mat", "price": 29.99, "category_id": 5, "brand": "FlexFit", "rating": 4.5, "stock": 180, "description": "6mm thick non-slip yoga mat with carrying strap."},
    {"id": 22, "name": "Resistance Bands Set", "price": 19.99, "category_id": 5, "brand": "PowerLoop", "rating": 4.3, "stock": 300, "description": "Set of 5 latex bands with varying resistance levels."},
    {"id": 23, "name": "Camping Tent (2-Person)", "price": 89.99, "category_id": 5, "brand": "TrailGuard", "rating": 4.4, "stock": 45, "description": "Lightweight waterproof tent with easy pop-up setup."},
    {"id": 24, "name": "Insulated Hiking Boots", "price": 119.99, "category_id": 5, "brand": "SummitStep", "rating": 4.6, "stock": 70, "description": "Waterproof leather boots with Vibram sole and thermal lining."},
    {"id": 25, "name": "Stainless Steel Tumbler", "price": 16.99, "category_id": 5, "brand": "HydroLife", "rating": 4.2, "stock": 260, "description": "20oz vacuum-insulated tumbler with spill-proof lid."},
]
