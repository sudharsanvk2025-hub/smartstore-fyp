# inventory.py
# Edit product names and prices to match your actual demo products

inventory = {
    "coke_can":      {"name": "Coke Can",      "price": 1.50, "stock": 10},
    "milo_carton":   {"name": "Milo Carton",   "price": 1.80, "stock": 8},
    "lays_chips":    {"name": "Lays Chips",    "price": 2.20, "stock": 12},
    "mineral_water": {"name": "Mineral Water", "price": 0.90, "stock": 15},
    "kelloggs":      {"name": "Kelloggs",      "price": 3.50, "stock": 6},
    "pocky":         {"name": "Pocky",         "price": 2.80, "stock": 10},
    "dutch_lady":    {"name": "Dutch Lady",    "price": 2.10, "stock": 8},
    "100plus":       {"name": "100 Plus",      "price": 1.60, "stock": 10},
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
    
    print("\nSimulating pickup of coke_can...")
    reduce_stock("coke_can")
    
    print("\nSimulating return of coke_can...")
    restore_stock("coke_can")
    
    print("\nLow stock items (threshold 3):")
    print(get_low_stock())