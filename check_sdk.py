import tastytrade
print("VERSION:", tastytrade.__version__ if hasattr(tastytrade, '__version__') else 'unknown')
print("TOP LEVEL:", [x for x in dir(tastytrade) if not x.startswith('_')])
try:
    from tastytrade import Session
    print("SESSION METHODS:", [x for x in dir(Session) if not x.startswith('_')])
except Exception as e:
    print("Session error:", e)