# basket.py
from inventory import reduce_stock, restore_stock, get_price

basket = {}  # { product_key: { name, price, qty } }

def add_item(name):
    """Called when YOLOv8 detects a product picked up"""
    from inventory import inventory
    if name not in inventory:
        print(f"[BASKET] Unknown product: {name}")
        return False

    reduce_stock(name)

    if name in basket:
        basket[name]["qty"] += 1
    else:
        basket[name] = {
            "name": inventory[name]["name"],
            "price": inventory[name]["price"],
            "qty": 1
        }
    print(f"[BASKET] Added {inventory[name]['name']} — qty: {basket[name]['qty']}")
    return True

def remove_item(name):
    """Called when product is returned to shelf"""
    from inventory import inventory
    if name not in basket:
        return False

    restore_stock(name)
    basket[name]["qty"] -= 1

    if basket[name]["qty"] <= 0:
        del basket[name]

    print(f"[BASKET] Removed {name}")
    return True

def get_basket():
    """Returns current basket contents"""
    return basket

def get_subtotal():
    return round(sum(v["price"] * v["qty"] for v in basket.values()), 2)

def get_gst():
    return round(get_subtotal() * 0.09, 2)

def get_total():
    return round(get_subtotal() + get_gst(), 2)

def clear_basket():
    """Called after payment confirmed"""
    basket.clear()
    print("[BASKET] Cleared — session ended")

def get_summary():
    return {
        "items":    list(basket.values()),
        "subtotal": get_subtotal(),
        "gst":      get_gst(),
        "total":    get_total()
    }

# Quick test
if __name__ == "__main__":
    print("Adding items to basket...")
    add_item("coke_can")
    add_item("lays_chips")
    add_item("coke_can")  # second one

    print("\nBasket contents:")
    for key, val in basket.items():
        print(f"  {val['name']} x{val['qty']} — ${val['price'] * val['qty']:.2f}")

    print(f"\nSubtotal: ${get_subtotal()}")
    print(f"GST (9%): ${get_gst()}")
    print(f"Total:    ${get_total()}")

    print("\nRemoving one coke_can...")
    remove_item("coke_can")

    print(f"\nNew total: ${get_total()}")

    print("\nClearing basket...")
    clear_basket()
    print(f"Basket after clear: {get_basket()}")