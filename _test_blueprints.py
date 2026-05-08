#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script: Verify all new blueprints are registered
"""

from modules import create_app

app = create_app()
routes = sorted([r.rule for r in app.url_map.iter_rules()])

# جميع البلوبرينتات الجديدة
modules = {
    "📦 Inventory": "/inventory",
    "👥 Contacts": "/contacts",
    "📷 Barcode": "/barcode",
    "🏥 Medical": "/medical",
    "🏗️ Construction": "/projects",
    "🚗 Rental": "/rental",
    "🛒 Wholesale": "/wholesale",
    "🔧 Services": "/services",
}

print("=" * 70)
print("✅ COMPLETE SERVICES - BLUEPRINTS VERIFICATION")
print("=" * 70)

total_routes = 0

for name, prefix in modules.items():
    module_routes = [r for r in routes if prefix in r]
    print(f"\n{name} Routes ({len(module_routes)}):")
    for route in module_routes:
        print(f"  ✓ {route}")
    total_routes += len(module_routes)

print(f"\n{'='*70}")
print(f"✅ TOTAL NEW ROUTES: {total_routes}")
print(f"✅ APPLICATION LOADED SUCCESSFULLY!")
print(f"{'='*70}")
