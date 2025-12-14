
import os
from stable_baselines3 import PPO
import sys

# Suppress warnings
import warnings
warnings.filterwarnings('ignore')

model_path = "d:/000-github-repositories/hybrid-trader-v03-03-higher-steps/models_hybrid_v4/best_tuned/sell/best_model.zip"

if not os.path.exists(model_path):
    print(f"Model not found at {model_path}")
else:
    try:
        model = PPO.load(model_path, device='cpu')
        print(f"Best Sell Model loaded successfully.")
        print(f"Total Timesteps: {model.num_timesteps}")
    except Exception as e:
        print(f"Error loading model: {e}")
