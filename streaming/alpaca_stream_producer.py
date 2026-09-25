"""
Connects to Alpaca's free real-time IEX websocket feed, subscribes to trades
and minute bars for a symbol list, validates each message against
schemas.py, and republishes it onto Kafka topics for the Snowflake Kafka
Connector to pick up (sql/02_bronze/bronze_tables.sql -> RAW_TRADES / RAW_BARS).

Docs: https://docs.alpaca.markets/us/docs/websocket-streaming
Requires a free Alpaca account (paper trading is enough) for an API key/secret:
https://alpaca.markets/

Env vars: ALPACA_API_KEY, ALPACA_API_SECRET
"""

import argparse
import json
import logging
import os

from kafka import KafkaProducer
from pydantic import ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed

from schemas import BarRecord, TradeRecord

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)r}',
)
logger = logging.getLogger("alpaca_stream_producer")

ALPACA_WS_URL = "wss://stream.data.alpaca.markets/v2/{feed}"


def to_trade_record(msg: dict) -> TradeRecord:
    # Pydantic parses Alpaca's RFC-3339 timestamps (e.g. "...123456789Z")
    # directly, truncating sub-microsecond precision Python can't represent.
    return TradeRecord(
        trade_id=str(msg["i"]),
        symbol=msg["S"],
        price=msg["p"],
        size=msg["s"],
        exchange_code=msg.get("x"),
        conditions=",".join(msg.get("c", [])),
        trade_ts=msg["t"],
    )


def to_bar_record(msg: dict) -> BarRecord:
    return BarRecord(
        symbol=msg["S"],
        bar_ts=msg["t"],
        open=msg["o"],
        high=msg["h"],
        low=msg["l"],
        close=msg["c"],
        volume=msg["v"],
        vwap=msg.get("vw"),
        trade_count=msg.get("n"),
    )


@retry(
    retry=retry_if_exception_type(ConnectionClosed),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def run(args, producer: KafkaProducer):
    api_key = os.environ["ALPACA_API_KEY"]
    api_secret = os.environ["ALPACA_API_SECRET"]

    url = ALPACA_WS_URL.format(feed=args.feed)
    with connect(url) as ws:
        ws.send(json.dumps({"action": "auth", "key": api_key, "secret": api_secret}))
        logger.info("auth response: %s", ws.recv())

        ws.send(json.dumps({"action": "subscribe", "trades": args.symbols, "bars": args.symbols}))
        logger.info("subscribe response: %s", ws.recv())

        for raw in ws:
            for msg in json.loads(raw):
                msg_type = msg.get("T")
                try:
                    if msg_type == "t":
                        record = to_trade_record(msg)
                        producer.send(
                            args.trades_topic,
                            value=record.model_dump(mode="json"),
                            key=record.symbol.encode("utf-8"),
                        )
                        logger.info("trade %s", record.model_dump_json())
                    elif msg_type == "b":
                        record = to_bar_record(msg)
                        producer.send(
                            args.bars_topic,
                            value=record.model_dump(mode="json"),
                            key=record.symbol.encode("utf-8"),
                        )
                        logger.info("bar %s", record.model_dump_json())
                    # other T values (success/error/subscription) are control messages
                except ValidationError as e:
                    # A malformed message shouldn't kill the stream; log and skip it.
                    logger.warning("dropping invalid message %s: %s", msg, e)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"])
    parser.add_argument("--feed", default="iex", choices=["iex", "sip", "delayed_sip"], help="iex is free")
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--trades-topic", default="market-trades")
    parser.add_argument("--bars-topic", default="market-bars")
    args = parser.parse_args()

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    run(args, producer)


if __name__ == "__main__":
    main()
