"""
Aether ML — Hybrid Prediction Engine for Behavioral Analytics & Web3 Data Intelligence.

Models:
  Edge (browser/mobile, <100ms):
    1. Intent Prediction   — GRU/LogReg predicting user's next action
    2. Bot Detection        — Random Forest behavioral biometrics classifier
    3. Session Scorer       — Logistic regression engagement + conversion scorer

  Server (SageMaker, high-throughput):
    4. Identity Resolution  — Graph Attention Network merging fragmented identities
    5. Journey Prediction   — Temporal Fusion Transformer for multi-step journey forecasting
    6. Churn Prediction     — XGBoost gradient boosted ensemble (30-day inactivity)
    7. LTV Prediction       — BG/NBD probabilistic + XGBoost regressor ensemble
    8. Anomaly Detection    — Isolation Forest + Autoencoder hybrid
    9. Campaign Attribution — Shapley value-based multi-touch attribution
"""

__version__ = "4.0.0"
