"""
Trains a real anomaly-detection model to replace/augment the fixed ">10%
one-minute move" rule behind fct_bars.is_suspect (dbt/models/marts/fct_bars.sql)
with something learned from actual bar-to-bar behavior per symbol, exports it
to ONNX, and registers it in Snowflake's Model Registry so it's callable
directly from SQL -- no external model-serving infra needed.

Why an isolation forest: it needs no labeled "this was fraud/bad data"
examples (we don't have any), it's fast enough to run as a batch UDF over
every bar, and unlike a fixed percentage threshold it can learn that some
symbols are normally more volatile than others -- a 5% move might be
routine for one stock and anomalous for another.

Why ONNX specifically: Snowflake's Model Registry runs ONNX models natively
as a warehouse UDF, so there's no separate model-serving container to deploy
or keep alive -- the model just becomes a SQL-callable function.

This script trains against the LOCAL offline sample data
(streaming/data/sample_bars.csv) so it's runnable without a live Snowflake
session; swap the `pd.read_csv(...)` block for a Snowpark DataFrame pulled
from MARKET_AGENT.GOLD.FCT_BARS once you have a live account (see the
commented-out block below).
"""

import logging

import numpy as np
import pandas as pd
from skl2onnx import to_onnx
from sklearn.ensemble import IsolationForest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_anomaly_model")

FEATURES = ["bar_return", "volume"]


def load_training_data(path: str = "../streaming/data/sample_bars.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    df["bar_return"] = (df["close"] - df["open"]) / df["open"]
    return df[FEATURES].dropna()

    # --- Live-account version (uncomment once Snowflake is set up) ---
    # from snowflake.snowpark import Session
    # session = Session.builder.configs(connection_parameters).create()
    # sdf = session.table("MARKET_AGENT.GOLD.FCT_BARS").select(
    #     ((col("CLOSE") - col("OPEN")) / col("OPEN")).alias("BAR_RETURN"), col("VOLUME")
    # )
    # return sdf.to_pandas()


def train(df: pd.DataFrame) -> IsolationForest:
    # contamination=0.02 says "expect ~2% of bars to be anomalous" -- a
    # starting assumption, not a measured fact; tune once real data exists.
    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42)
    model.fit(df[FEATURES].values)
    logger.info("trained on %d rows", len(df))
    return model


def export_to_onnx(model: IsolationForest, path: str = "anomaly_model.onnx") -> None:
    # target_opset pins the ai.onnx.ml domain version explicitly -- without
    # it, skl2onnx picks whatever the installed onnx package defaults to,
    # which can be newer than skl2onnx's own converter supports (hit exactly
    # this running it locally: "version 4 ... not supported yet").
    onnx_model = to_onnx(
        model,
        X=np.zeros((1, len(FEATURES)), dtype=np.float32),
        target_opset={"": 18, "ai.onnx.ml": 3},
    )
    with open(path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    logger.info("wrote %s", path)


def register_to_snowflake(onnx_path: str) -> None:
    """
    Registers the ONNX file in Snowflake's Model Registry. Requires a live
    Snowpark session -- left as a documented function rather than run
    automatically, since it needs real credentials this repo doesn't have.
    """
    # from snowflake.snowpark import Session
    # from snowflake.ml.registry import Registry
    # import onnx
    #
    # session = Session.builder.configs(connection_parameters).create()
    # registry = Registry(session=session, database_name="MARKET_AGENT", schema_name="GOLD")
    # onnx_model = onnx.load(onnx_path)
    # registry.log_model(
    #     onnx_model,
    #     model_name="BAR_ANOMALY_DETECTOR",
    #     version_name="v1",
    #     comment="IsolationForest over (bar_return, volume); replaces the fixed 10% threshold in fct_bars.is_suspect",
    # )
    #
    # Once registered, call it from SQL, e.g.:
    #   SELECT symbol, bar_ts,
    #          MARKET_AGENT.GOLD.BAR_ANOMALY_DETECTOR!PREDICT(bar_return, volume) AS ml_is_suspect
    #   FROM MARKET_AGENT.GOLD.FCT_BARS;
    raise NotImplementedError(
        "Uncomment the block above once a live Snowflake session is available; "
        "left as documentation until then."
    )


if __name__ == "__main__":
    data = load_training_data()
    model = train(data)
    export_to_onnx(model)
    logger.info("model trained and exported. Run register_to_snowflake() once Snowflake is connected.")
