"""
Background-style training trigger for scheduled execution.

Example cron / task usage:
  python train_worker.py
"""

import logging
import config
from ml_trainer import auto_train_if_due


def main():
    logging.basicConfig(level=logging.INFO)
    result = auto_train_if_due(
        db_path=config.DB_PATH,
        min_total_trades=config.MIN_TRADES_FOR_TRAINING,
        min_new_trades=20,
        retrain_every_days=1,
    )
    print(result)


if __name__ == "__main__":
    main()
