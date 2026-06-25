import tastytrade

# Account module
try:
    from tastytrade import Account
    print("ACCOUNT METHODS:", [x for x in dir(Account) if not x.startswith('_')])
except Exception as e:
    print("Account error:", e)

# Order module
try:
    import tastytrade.order as order_mod
    print("\nORDER MODULE:", [x for x in dir(order_mod) if not x.startswith('_')])
except Exception as e:
    print("Order error:", e)

# Check for market data / instruments
try:
    import tastytrade.instruments as inst_mod
    print("\nINSTRUMENTS MODULE:", [x for x in dir(inst_mod) if not x.startswith('_')])
except Exception as e:
    print("Instruments error:", e)

try:
    import tastytrade.dxfeed as dx
    print("\nDXFEED MODULE:", [x for x in dir(dx) if not x.startswith('_')])
except Exception as e:
    print("dxfeed error:", e)

# Look for candle/history/quote functions
import pkgutil, tastytrade as tt
for importer, modname, ispkg in pkgutil.walk_packages(path=tt.__path__, prefix=tt.__name__+'.', onerror=lambda x: None):
    print("MODULE:", modname)