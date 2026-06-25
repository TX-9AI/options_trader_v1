import inspect
from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Candle

# DXLinkStreamer signatures
print("=== DXLinkStreamer.__init__ ===")
print(inspect.signature(DXLinkStreamer.__init__))

print("\n=== DXLinkStreamer.subscribe_candle ===")
print(inspect.signature(DXLinkStreamer.subscribe_candle))

print("\n=== DXLinkStreamer.subscribe ===")
print(inspect.signature(DXLinkStreamer.subscribe))

print("\n=== DXLinkStreamer.listen ===")
print(inspect.signature(DXLinkStreamer.listen))

print("\n=== DXLinkStreamer.get_event ===")
print(inspect.signature(DXLinkStreamer.get_event))

# Candle streamer symbol format
print("\n=== Candle event_symbol format example ===")
print("Candle streamer_symbol format: QQQ{=5m} or QQQ{=1d} etc")

# Check if there's a market_sessions or history endpoint
import tastytrade.market_sessions as ms
print("\n=== get_market_sessions signature ===")
print(inspect.signature(ms.get_market_sessions))

# Check search module
import tastytrade.search as search
print("\n=== search module ===")
print([x for x in dir(search) if not x.startswith('_')])

# Check utils
import tastytrade.utils as utils
print("\n=== utils module ===")
print([x for x in dir(utils) if not x.startswith('_')])

# Check paper module
import tastytrade.paper as paper
print("\n=== paper module ===")
print([x for x in dir(paper) if not x.startswith('_')])

# Check Account.get_history signature
from tastytrade import Account
print("\n=== Account.get_history signature ===")
print(inspect.signature(Account.get_history))

print("\n=== Account.get_positions return type ===")
import tastytrade.account as acct
print([x for x in dir(acct) if not x.startswith('_')])

# CurrentPosition fields
try:
    from tastytrade.account import CurrentPosition
    print("\n=== CurrentPosition model_fields ===")
    print(list(CurrentPosition.model_fields.keys()))
except Exception as e:
    print("CurrentPosition error:", e)

# PlacedOrderResponse fields
from tastytrade.order import PlacedOrderResponse, PlacedOrder
print("\n=== PlacedOrderResponse model_fields ===")
print(list(PlacedOrderResponse.model_fields.keys()))

print("\n=== PlacedOrder model_fields ===")
print(list(PlacedOrder.model_fields.keys()))