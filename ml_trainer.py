"""
ml_trainer.py — Machine Learning Training Engine

Self-learning system for maximum profit optimization.
Target: >70% accuracy, >15% monthly returns
"""

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, mean_absolute_error, r2_score
from xgboost import XGBClassifier, XGBRegressor
import joblib
from datetime import datetime, date
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
            df = pd.DataFrame([features])[self.features].fillna(0)
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
            df = pd.DataFrame([features])[self.features].fillna(0)
            scaled = self.scaler.transform(df)
            profit = self.profit_model.predict(scaled)[0]
            return float(profit)
        except:
            return 0.0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    trainer = MLTrainer("meezan_v3.db")
    
    try:
        results = trainer.train_all()
        for r in results:
            print(f"\n{r['model']}: {r}")
    except ValueError as e:
        print(f"Need more trades: {e}")
