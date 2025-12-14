# -*- coding: utf-8 -*-
"""
MC Dropout CV 分佈分析腳本
用於測試 T+1, T+5 和 T+20 模型的 MC Dropout 變異係數 (CV) 分佈

目的：
- 了解目前 T+1 模型是否有 Dropout（無 Dropout 則 CV = 0）
- 比較 T+1, T+5, T+20 的 CV 分佈差異
- 為信心度門檻設定提供數據依據

使用方式：
  python analyze_cv_distribution.py
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import date
from pathlib import Path

# 抑制 TensorFlow 警告
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# 載入模型
# =============================================================================
def load_models():
    """載入 T+1 和 T+5 LSTM 模型"""
    import twii_model_registry_multivariate as lstm_1d_module
    import twii_model_registry_5d as lstm_5d_module
    import twii_model_registry_20d as lstm_20d_module
    
    print("=" * 60)
    print("📦 載入 LSTM 模型")
    print("=" * 60)
    
    # T+1 模型
    meta_1d = lstm_1d_module.select_best_model(date.today())
    if meta_1d is None:
        raise RuntimeError("找不到 T+1 模型")
    model_1d, scaler_feat_1d, scaler_tgt_1d, _ = lstm_1d_module.load_artifacts(
        meta_1d['train_start'], meta_1d['train_end'])
    print(f"✅ T+1 Model: {meta_1d['train_start']} ~ {meta_1d['train_end']}")
    print(f"   Lookback: {meta_1d.get('lookback', 10)}")
    
    # T+5 模型
    meta_5d = lstm_5d_module.select_best_model(date.today())
    if meta_5d is None:
        raise RuntimeError("找不到 T+5 模型")
    model_5d, scaler_feat_5d, scaler_tgt_5d, _ = lstm_5d_module.load_artifacts(
        meta_5d['train_start'], meta_5d['train_end'])
    print(f"✅ T+5 Model: {meta_5d['train_start']} ~ {meta_5d['train_end']}")
    print(f"   Lookback: {meta_5d.get('lookback', 30)}")
    print(f"   Dropout Rate: {meta_5d.get('dropout_rate', 'N/A')}")
    
    # T+20 模型
    meta_20d = lstm_20d_module.select_best_model(date.today())
    if meta_20d is None:
        print("⚠️ 找不到 T+20 模型 (可能尚未訓練)")
        model_20d, scaler_feat_20d, scaler_tgt_20d, _ = None, None, None, {}
    else:
        model_20d, scaler_feat_20d, scaler_tgt_20d, _ = lstm_20d_module.load_artifacts(
            meta_20d['train_start'], meta_20d['train_end'])
        print(f"✅ T+20 Model: {meta_20d['train_start']} ~ {meta_20d['train_end']}")
        print(f"   Lookback: {meta_20d.get('lookback', 60)}")
        print(f"   Dropout Rate: {meta_20d.get('dropout_rate', 'N/A')}")
    
    models = {
        '1d': {'model': model_1d, 'scaler_feat': scaler_feat_1d, 
               'scaler_tgt': scaler_tgt_1d, 'meta': meta_1d},
        '5d': {'model': model_5d, 'scaler_feat': scaler_feat_5d, 
               'scaler_tgt': scaler_tgt_5d, 'meta': meta_5d}
    }
    
    if model_20d:
        models['20d'] = {'model': model_20d, 'scaler_feat': scaler_feat_20d,
                         'scaler_tgt': scaler_tgt_20d, 'meta': meta_20d}
        
    return models


def load_test_data():
    """載入測試資料（最近 100 天）"""
    import twii_model_registry_multivariate as lstm_1d_module
    
    print("\n📊 載入測試資料...")
    df = lstm_1d_module.load_recent_data(lookback_days=100)
    df = lstm_1d_module.add_technical_indicators(df)
    
    if 'Adj Close' not in df.columns:
        df['Adj Close'] = df['Close']
    
    print(f"✅ 測試資料筆數: {len(df)}")
    print(f"   日期範圍: {df.index[0].date()} ~ {df.index[-1].date()}")
    
    return df


def run_mc_analysis(models: dict, df: pd.DataFrame, n_iter: int = 30):
    """
    執行 MC Dropout 分析
    
    對每個模型進行 n_iter 次預測，計算 CV 分佈
    """
    feature_cols = ['Adj Close', 'Volume_Log', 'K', 'D', 'MACD_Hist']
    features = df[feature_cols].values
    
    results = {}
    
    for model_name, model_data in models.items():
        model = model_data['model']
        scaler_feat = model_data['scaler_feat']
        scaler_tgt = model_data['scaler_tgt']
        lookback = model_data['meta'].get('lookback', 10 if model_name == '1d' else (60 if model_name == '20d' else 30))
        
        print(f"\n🔬 分析 T+{model_name.replace('d', '')} 模型 (MC Dropout x{n_iter})...")
        
        # 縮放特徵
        scaled_features = scaler_feat.transform(features)
        
        # 建立批次輸入
        batch = []
        for i in range(lookback, len(scaled_features)):
            batch.append(scaled_features[i - lookback:i])
        batch = np.array(batch)
        
        print(f"   批次形狀: {batch.shape}")
        
        # MC Dropout 採樣
        mc_results = []
        for i in range(n_iter):
            # 使用 training=True 啟用 Dropout（若模型有 Dropout 層）
            preds_scaled = model(batch, training=True).numpy()
            preds = scaler_tgt.inverse_transform(preds_scaled).flatten()
            mc_results.append(preds)
        
        mc_results = np.array(mc_results)  # shape: (n_iter, n_samples)
        
        # 計算統計量
        mc_mean = np.mean(mc_results, axis=0)
        mc_std = np.std(mc_results, axis=0)
        
        # 計算 CV (Coefficient of Variation)
        # CV = std / mean，但避免除以零
        cv = np.where(mc_mean > 0, mc_std / mc_mean, 0)
        
        results[model_name] = {
            'mc_mean': mc_mean,
            'mc_std': mc_std,
            'cv': cv,
            'n_samples': len(mc_mean)
        }
        
        # 輸出統計摘要
        print(f"\n   📈 CV 分佈統計 (T+{model_name.replace('d', '')}):")
        print(f"   ─────────────────────────────────")
        print(f"   樣本數: {len(cv)}")
        print(f"   CV 最小值: {cv.min():.6f} ({cv.min() * 100:.4f}%)")
        print(f"   CV 最大值: {cv.max():.6f} ({cv.max() * 100:.4f}%)")
        print(f"   CV 平均值: {cv.mean():.6f} ({cv.mean() * 100:.4f}%)")
        print(f"   CV 中位數: {np.median(cv):.6f} ({np.median(cv) * 100:.4f}%)")
        print(f"   CV 標準差: {cv.std():.6f}")
        
        # 百分位數分佈
        percentiles = [10, 25, 50, 75, 90, 95, 99]
        print(f"\n   📊 CV 百分位數:")
        for p in percentiles:
            val = np.percentile(cv, p)
            print(f"      P{p:02d}: {val:.6f} ({val * 100:.4f}%)")
    
    return results


def suggest_thresholds(results: dict):
    """根據 CV 分佈建議信心度門檻"""
    print("\n" + "=" * 60)
    print("💡 信心度門檻建議")
    print("=" * 60)
    
    for model_name, data in results.items():
        cv = data['cv']
        
        # 如果 CV 全部為 0，表示模型沒有 Dropout
        if cv.max() < 1e-10:
            print(f"\n⚠️  T+{model_name.replace('d', '')} 模型:")
            print(f"   CV 全部為 0！這表示模型 **沒有 Dropout 層**。")
            print(f"   建議：修改模型架構加入 Dropout 後重新訓練。")
            continue
        
        # 使用百分位數設定門檻
        p10 = np.percentile(cv, 10)  # 高信心門檻
        p90 = np.percentile(cv, 90)  # 低信心門檻
        
        print(f"\n📐 T+{model_name.replace('d', '')} 模型建議門檻:")
        print(f"   ─────────────────────────────────")
        print(f"   threshold_high (高信心): {p10:.6f} (P10)")
        print(f"   threshold_low (低信心):  {p90:.6f} (P90)")
        print(f"\n   信心度公式:")
        print(f"   score = 1.0 - (cv - {p10:.6f}) / ({p90:.6f} - {p10:.6f})")
        print(f"   confidence = clip(score, 0.0, 1.0)")
        
        # 與 T+5 目前設定比較（若為 5d 模型）
        if model_name == '5d':
            print(f"\n   📌 目前 T+5 門檻設定:")
            print(f"      threshold_high = 0.001 (0.1%)")
            print(f"      threshold_low  = 0.010 (1.0%)")
        elif model_name == '1d':
             print(f"\n   📌 目前 T+1 門檻設定: 0.8% ~ 4.0%")
        elif model_name == '20d':
             print(f"\n   📌 目前 T+20 門檻設定: 1.0% ~ 5.0%")


def main():
    print("\n" + "=" * 60)
    print("🔍 MC Dropout CV 分佈分析")
    print("=" * 60)
    
    # 1. 載入模型
    models = load_models()
    
    # 2. 載入測試資料
    df = load_test_data()
    
    # 3. 執行 MC 分析
    results = run_mc_analysis(models, df, n_iter=30)
    
    # 4. 建議門檻
    suggest_thresholds(results)
    
    print("\n" + "=" * 60)
    print("✅ 分析完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
