from tastytrade import Session
from tastytrade.instruments import Option, NestedOptionChain, NestedOptionChainExpiration, Strike, get_option_chain
from tastytrade.dxfeed import Candle, Quote, Greeks
from tastytrade.order import NewOrder, Leg, OrderAction, OrderType, OrderTimeInForce, PriceEffect, InstrumentType
from tastytrade.market_data import get_market_data, get_market_data_by_type, MarketData
from tastytrade.metrics import get_market_metrics, MarketMetricInfo, OptionExpirationImpliedVolatility
import tastytrade.market_data as md
import inspect

# Option model fields
print("=== Option model_fields ===")
print(list(Option.model_fields.keys()))

# Strike model fields  
print("\n=== Strike model_fields ===")
print(list(Strike.model_fields.keys()))

# NestedOptionChain fields
print("\n=== NestedOptionChain model_fields ===")
print(list(NestedOptionChain.model_fields.keys()))

# NestedOptionChainExpiration fields
print("\n=== NestedOptionChainExpiration model_fields ===")
print(list(NestedOptionChainExpiration.model_fields.keys()))

# Candle fields
print("\n=== Candle model_fields ===")
print(list(Candle.model_fields.keys()))

# Quote fields
print("\n=== Quote model_fields ===")
print(list(Quote.model_fields.keys()))

# Greeks fields
print("\n=== Greeks model_fields ===")
print(list(Greeks.model_fields.keys()))

# NewOrder fields
print("\n=== NewOrder model_fields ===")
print(list(NewOrder.model_fields.keys()))

# Leg fields
print("\n=== Leg model_fields ===")
print(list(Leg.model_fields.keys()))

# MarketData fields
print("\n=== MarketData model_fields ===")
print(list(MarketData.model_fields.keys()))

# MarketMetricInfo fields
print("\n=== MarketMetricInfo model_fields ===")
print(list(MarketMetricInfo.model_fields.keys()))

# get_market_data signature
print("\n=== get_market_data signature ===")
print(inspect.signature(get_market_data))

# get_market_data_by_type signature
print("\n=== get_market_data_by_type signature ===")
print(inspect.signature(get_market_data_by_type))

# get_option_chain signature
print("\n=== get_option_chain signature ===")
print(inspect.signature(get_option_chain))

# get_market_metrics signature
print("\n=== get_market_metrics signature ===")
print(inspect.signature(get_market_metrics))

# DXLinkStreamer
from tastytrade import DXLinkStreamer
print("\n=== DXLinkStreamer methods ===")
print([x for x in dir(DXLinkStreamer) if not x.startswith('_')])

# Account.get and place_order signatures
from tastytrade import Account
print("\n=== Account.get signature ===")
print(inspect.signature(Account.get))
print("\n=== Account.place_order signature ===")
print(inspect.signature(Account.place_order))
print("\n=== Account.get_positions signature ===")
print(inspect.signature(Account.get_positions))

# PriceEffect values
print("\n=== PriceEffect values ===")
print(list(PriceEffect))

# InstrumentType values
print("\n=== InstrumentType values ===")
print(list(InstrumentType))