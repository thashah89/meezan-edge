"""
ml_trainer.py — Machine Learning Training Engine

Self-learning system for maximum profit optimization.
Target: >70% accuracy, >15% monthly returns
"""

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, mean_absolute_error, r2_score
from xgboost import XGBClassifier, XGBRegressor
import joblib
from datetime import datetime, date, timedelta
import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

MODELS_DIR = Path("models")
MODELS_DIR.mkdir(exist_ok=True)


class MLTrainer:
    """ML training with profit maximization focus."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.scaler = StandardScaler()
    
    def load_data(self, min_trades: int = 100) -> pd.DataFrame:
        """Load completed trades."""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql("""
            SELECT * FROM trades_simulated
            WHERE status IN ('win', 'loss')
            AND entry_rsi IS NOT NULL
        """, conn)
        conn.close()
        
        if len(df) < min_trades:
            raise ValueError(f"Need {min_trades} trades, have {len(df)}")
        
        return df
    
    def extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Feature engineering for max predictive power."""
        X = pd.DataFrame()
        
        # Core indicators
        X['rsi'] = df['entry_rsi']
        X['adx'] = df['entry_adx']
        X['trend_score'] = df['entry_trend_score']
        X['rr_ratio'] = df['rr_ratio']
        
        # Derived features
        X['rsi_oversold'] = (df['entry_rsi'] < 30).astype(int)
        X['rsi_overbought'] = (df['entry_rsi'] > 70).astype(int)
        X['adx_strong'] = (df['entry_adx'] > 30).astype(int)
        X['strong_trend'] = (df['entry_trend_score'] > 70).astype(int)
        
        # Mode
        X['is_intraday'] = (df['mode'] == 'intraday').astype(int)
        
        # Interactions
        X['rsi_adx'] = df['entry_rsi'] * df['entry_adx'] / 100
        
        return X.fillna(0)
    
    def train_win_model(self, df: pd.DataFrame) -> dict:
        """Train win probability classifier (TARGET: >70% accuracy)."""
        log.info("Training Win Probability Model...")
        
        X = self.extract_features(df)
        y = (df['status'] == 'win').astype(int)
        
        X_scaled = self.scaler.fit_transform(X)
        X_train, X_test, y_train, y_test = train_test_split(
            X_scaled, y, test_size=0.2, random_state=42, stratify=y
        )
        
        # Optimized XGB for accuracy
        model = XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42
        )
        
        model.fit(X_train, y_train)
        
        y_pred = model.predict(X_test)
        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred)
        rec = recall_score(y_test, y_pred)
        
        log.info(f"Win Model: {acc:.1%} accuracy, {prec:.1%} precision")
        
        # Save
        joblib.dump(model, MODELS_DIR / "win_probability.joblib")
        joblib.dump(self.scaler, MODELS_DIR / "scaler.joblib")
        joblib.dump(X.columns.tolist(), MODELS_DIR / "features.joblib")
        
        return {
            'model': 'win_probability',
            'accuracy': acc,
            'precision': prec,
            'recall': rec,
            'samples': len(X_test)
        }
    
    def train_profit_model(self, df: pd.DataFrame) -> dict:
        """Train profit expectation regressor."""
        log.info("Training Profit Model...")
        
        X = self.extract_features(df)
        y = df['profit_pct']
        
        X_scaled = self.scaler.transform(X)
        X_train, X_test, y_train, y_test = train_test_split(
            X_scaled, y, test_size=0.2, random_state=42
        )
        
        model = XGBRegressor(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            random_state=42
        )
        
        model.fit(X_train, y_train)
        
        y_pred = model.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        
        log.info(f"Profit Model: MAE {mae:.2f}%, R² {r2:.3f}")
        
        joblib.dump(model, MODELS_DIR / "profit_expectation.joblib")
        
        return {'model': 'profit_expectation', 'mae': mae, 'r2': r2}
    
    def train_all(self):
        """Train all models."""
        df = self.load_data()
        
        results = []
        results.append(self.train_win_model(df))
        results.append(self.train_profit_model(df))
        self._update_pattern_signals(df)
        
        # Log to DB
        self._log_results(results)
        
        return results
    
    def _log_results(self, results: list):
        """Save training results to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for r in results:
            cursor.execute("""
                INSERT INTO ai_model_logs
                (model_name, training_date, accuracy, mae, r2_score, dataset_size)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                r['model'],
                date.today(),
                r.get('accuracy'),
                r.get('mae'),
                r.get('r2'),
                r.get('samples', 0)
            ))
        
        conn.commit()
        conn.close()

    def _update_pattern_signals(self, df: pd.DataFrame):
        """
        Build coarse pattern stats from completed trades for backend learning.
        """
        if df.empty:
            return

        def bucket_rsi(v):
            if pd.isna(v):
                return "rsi_unknown"
            if v < 35:
                return "rsi_low"
            if v > 65:
                return "rsi_high"
            return "rsi_mid"

        def bucket_adx(v):
            if pd.isna(v):
                return "adx_unknown"
            if v < 20:
                return "adx_weak"
            if v > 30:
                return "adx_strong"
            return "adx_mid"

        def bucket_trend(v):
            if pd.isna(v):
                return "trend_unknown"
            if v < 45:
                return "trend_low"
            if v > 65:
                return "trend_high"
            return "trend_mid"

        patt = df.copy()
        patt["p_rsi"] = patt["entry_rsi"].apply(bucket_rsi)
        patt["p_adx"] = patt["entry_adx"].apply(bucket_adx)
        patt["p_trend"] = patt["entry_trend_score"].apply(bucket_trend)
        patt["p_mode"] = patt["mode"].fillna("unknown")
        patt["pattern_key"] = (
            patt["p_rsi"].astype(str) + "|" +
            patt["p_adx"].astype(str) + "|" +
            patt["p_trend"].astype(str) + "|" +
            patt["p_mode"].astype(str)
        )
        patt["is_win"] = (patt["status"] == "win").astype(int)
        patt["profit_pct"] = patt["profit_pct"].fillna(0.0)

        agg = patt.groupby("pattern_key", as_index=False).agg(
            trades=("pattern_key", "count"),
            wins=("is_win", "sum"),
            avg_return=("profit_pct", "mean"),
        )
        agg["win_rate"] = np.where(agg["trades"] > 0, agg["wins"] / agg["trades"], 0.0)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pattern_signals (
                    pattern_key TEXT PRIMARY KEY,
                    trades INTEGER,
                    wins INTEGER,
                    win_rate REAL,
                    avg_return REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            for _, row in agg.iterrows():
                cur.execute(
                    """
                    INSERT OR REPLACE INTO pattern_signals
                    (pattern_key, trades, wins, win_rate, avg_return, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        str(row["pattern_key"]),
                        int(row["trades"]),
                        int(row["wins"]),
                        float(row["win_rate"]),
                        float(row["avg_return"]),
                    ),
                )
            conn.commit()
        finally:
            conn.close()


class MLPredictor:
    """Use trained models for predictions."""
    
    def __init__(self):
        self.models_loaded = False
        try:
            self.win_model = joblib.load(MODELS_DIR / "win_probability.joblib")
            self.profit_model = joblib.load(MODELS_DIR / "profit_expectation.joblib")
            self.scaler = joblib.load(MODELS_DIR / "scaler.joblib")
            self.features = joblib.load(MODELS_DIR / "features.joblib")
            self.models_loaded = True
            log.info("ML models loaded")
        except:
            log.warning("ML models not found - using defaults")
    
    def predict_win_prob(self, features: dict) -> float:
        """Predict win probability."""
        if not self.models_loaded:
            return 0.50
        
        try:
            df = pd.DataFrame([features]).reindex(columns=self.features, fill_value=0).fillna(0)
            scaled = self.scaler.transform(df)
            prob = self.win_model.predict_proba(scaled)[0, 1]
            return float(prob)
        except:
            return 0.50
    
    def predict_profit(self, features: dict) -> float:
        """Predict expected profit %."""
        if not self.models_loaded:
            return 0.0
        
        try:
            df = pd.DataFrame([features]).reindex(columns=self.features, fill_value=0).fillna(0)
            scaled = self.scaler.transform(df)
            profit = self.profit_model.predict(scaled)[0]
            return float(profit)
        except:
            return 0.0


def auto_train_if_due(
    db_path: str,
    min_total_trades: int = 100,
    min_new_trades: int = 20,
    retrain_every_days: int = 1,
) -> dict:
    """
    Backend-friendly retrain trigger.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COUNT(*) FROM trades_simulated
            WHERE status IN ('win', 'loss') AND entry_rsi IS NOT NULL
        """)
        total = int(cur.fetchone()[0] or 0)
        if total < min_total_trades:
            return {"trained": False, "reason": f"need_{min_total_trades}_trades_have_{total}"}

        cur.execute("""
            SELECT training_date, dataset_size
            FROM ai_model_logs
            ORDER BY training_date DESC, id DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            last_train_date = datetime.strptime(row[0], "%Y-%m-%d").date() if isinstance(row[0], str) else row[0]
            last_size = int(row[1] or 0)
        else:
            last_train_date = None
            last_size = 0

        if last_train_date and (date.today() - last_train_date) < timedelta(days=retrain_every_days):
            if total - last_size < min_new_trades:
                return {"trained": False, "reason": "not_due"}
    finally:
        conn.close()

    trainer = MLTrainer(db_path)
    results = trainer.train_all()
    return {"trained": True, "results": results}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    trainer = MLTrainer("meezan_v3.db")
    
    try:
        results = trainer.train_all()
        for r in results:
            print(f"\n{r['model']}: {r}")
    except ValueError as e:
        print(f"Need more trades: {e}")
