"""
Connects to Alpaca's free real-time IEX websocket feed, subscribes to trades
and minute bars for a symbol list, and republishes each message onto Kafka
topics after remapping field names onto this project's Bronze schema
(sql/02_bronze/bronze_tables.sql -> RAW_TRADES / RAW_BARS).

Docs: https://docs.alpaca.markets/us/docs/websocket-streaming
Requires a free Alpaca account (paper trading is enough) for an API key/secret:
https://alpaca.markets/

Env vars: ALPACA_API_KEY, ALPACA_API_SECRET
"""

import argparse
import json
import os

from kafka import KafkaProducer
from websockets.sync.client import connect

ALPACA_WS_URL = "wss://stream.data.alpaca.markets/v2/{feed}"


def to_trade_record(msg: dict) -> dict:
    return {
        "trade_id": str(msg["i"]),
        "symbol": msg["S"],
        "price": msg["p"],
        "size": msg["s"],
        "exchange_code": msg.get("x"),
        "conditions": ",".join(msg.get("c", [])),
        "trade_ts": msg["t"],
    }


def to_bar_record(msg: dict) -> dict:
    return {
        "symbol": msg["S"],
        "bar_ts": msg["t"],
        "open": msg["o"],
        "high": msg["h"],
        "low": msg["l"],
        "close": msg["c"],
        "volume": msg["v"],
        "vwap": msg.get("vw"),
        "trade_count": msg.get("n"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"])
    parser.add_argument("--feed", default="iex", choices=["iex", "sip", "delayed_sip"], help="iex is free")
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--trades-topic", default="market-trades")
    parser.add_argument("--bars-topic", default="market-bars")
    args = parser.parse_args()

    api_key = os.environ["ALPACA_API_KEY"]
    api_secret = os.environ["ALPACA_API_SECRET"]

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    url = ALPACA_WS_URL.format(feed=args.feed)
    with connect(url) as ws:
        ws.send(json.dumps({"action": "auth", "key": api_key, "secret": api_secret}))
        print("auth ->", ws.recv())

        ws.send(json.dumps({"action": "subscribe", "trades": args.symbols, "bars": args.symbols}))
        print("subscribe ->", ws.recv())

        for raw in ws:
            for msg in json.loads(raw):
                msg_type = msg.get("T")
                if msg_type == "t":
                    record = to_trade_record(msg)
                    producer.send(args.trades_topic, value=record, key=record["symbol"].encode("utf-8"))
                    print("trade", record)
                elif msg_type == "b":
                    record = to_bar_record(msg)
                    producer.send(args.bars_topic, value=record, key=record["symbol"].encode("utf-8"))
                    print("bar", record)
                # other T values (success/error/subscription) are control messages, not data


if __name__ == "__main__":
    main()
