# inventory.py
# Keys must match the YOLO class names exactly (Roboflow class names)

inventory = {
    "webcam_box":     {"name": "Webcam Box",                    "price": 5.00, "stock": 5},
    "roller_coaster": {"name": "Roller Coaster BBQ",            "price": 1.20, "stock": 8},
    "popo_murukku":   {"name": "Popo Fish Murukku",             "price": 1.50, "stock": 8},
    "pocky":          {"name": "Pocky Cookies & Cream",         "price": 2.30, "stock": 10},
    "salted_peanuts": {"name": "Salted Peanuts",                "price": 1.80, "stock": 8},
    "ice_mountain":   {"name": "Ice Mountain Mineral Water",    "price": 0.90, "stock": 12},
}

def reduce_stock(name):
    """Call this when a product is picked up"""
    if name in inventory and inventory[name]["stock"] > 0:
        inventory[name]["stock"] -= 1
        print(f"[STOCK] {name} picked up — {inventory[name]['stock']} remaining")
        return True
    return False

def restore_stock(name):
    """Call this when a product is returned to shelf"""
    if name in inventory:
        inventory[name]["stock"] += 1
        print(f"[STOCK] {name} returned — {inventory[name]['stock']} remaining")

def get_inventory():
    """Returns full inventory — used by dashboard"""
    return inventory

def get_price(name):
    """Returns price of a product"""
    return inventory.get(name, {}).get("price", 0)

def get_low_stock(threshold=3):
    """Returns products running low — useful for dashboard warning"""
    return {k: v for k, v in inventory.items() if v["stock"] <= threshold}

# Quick test
if __name__ == "__main__":
    print("Current inventory:")
    for key, val in inventory.items():
        print(f"  {val['name']}: {val['stock']} units @ ${val['price']:.2f}")
    
    print("\nSimulating pickup of pocky...")
    reduce_stock("pocky")
    
    print("\nSimulating return of pocky...")
    restore_stock("pocky")
    
    print("\nLow stock items (threshold 3):")
    print(get_low_stock())