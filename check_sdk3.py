# Inspect the key modules we need for market data, options chain, and orders

import tastytrade.market_data as md
print("MARKET_DATA MODULE:", [x for x in dir(md) if not x.startswith('_')])

import tastytrade.metrics as metrics
print("\nMETRICS MODULE:", [x for x in dir(metrics) if not x.startswith('_')])

import tastytrade.market_sessions as ms
print("\nMARKET_SESSIONS MODULE:", [x for x in dir(ms) if not x.startswith('_')])

from tastytrade.instruments import NestedOptionChain, NestedOptionChainExpiration, get_option_chain, Option
print("\nget_option_chain:", get_option_chain.__doc__)
print("Option fields:", [x for x in dir(Option) if not x.startswith('_')][:30])

from tastytrade.order import NewOrder, Leg, OrderAction, OrderType, OrderTimeInForce, PriceEffect
print("\nNewOrder fields:", [x for x in dir(NewOrder) if not x.startswith('_')][:20])
print("Leg fields:", [x for x in dir(Leg) if not x.startswith('_')][:20])
print("OrderAction values:", list(OrderAction))
print("OrderType values:", list(OrderType))
print("OrderTimeInForce values:", list(OrderTimeInForce))

from tastytrade.dxfeed import Candle, Quote, Greeks
print("\nCandle fields:", [x for x in dir(Candle) if not x.startswith('_')][:20])
print("Quote fields:", [x for x in dir(Quote) if not x.startswith('_')][:20])
print("Greeks fields:", [x for x in dir(Greeks) if not x.startswith('_')][:20])