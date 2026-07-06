import json
import numpy as np
import scipy.stats as stats
import os
from collections import defaultdict

file_path = os.path.join("data_lake", "sentiment_factor_news", "feed", "classified_news.jsonl")

items = []
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
except Exception as e:
    print(f"Error reading data: {e}")

# Dự án bạn lưu tin theo dạng append, nên các tin cuối cùng là tin mới nhất.
# Theo latest.json, 1 ngày thường có khoảng 120-150 tin. Ta lấy 130 tin mới nhất (tương đương 1 ngày).
recent_items = items[-130:] if len(items) > 130 else items

# Nhóm điểm số theo từng kênh và tất cả vào macro composite
channels_raw_scores = defaultdict(list)
all_scores = []

for item in recent_items:
    score = item.get("final_score")
    if score is not None:
        channel = item.get("macro_channel", "unknown")
        channels_raw_scores[channel].append(score)
        all_scores.append(score)

# MCMC setup
def log_prior(mu):
    return stats.norm.logpdf(mu, loc=0, scale=1.0)

def log_likelihood(mu, data):
    return np.sum(stats.norm.logpdf(data, loc=mu, scale=0.5))

def log_posterior(mu, data):
    return log_prior(mu) + log_likelihood(mu, data)

def mcmc_sample(data, iterations=5000):
    if len(data) == 0:
        return np.zeros(iterations)
    
    samples = np.zeros(iterations)
    current_mu = 0.0
    current_log_post = log_posterior(current_mu, data)
    
    for i in range(iterations):
        proposed_mu = np.random.normal(loc=current_mu, scale=0.2)
        proposed_log_post = log_posterior(proposed_mu, data)
        
        diff = proposed_log_post - current_log_post
        if diff > 0:
            acceptance_ratio = 1.0
        else:
            acceptance_ratio = np.exp(diff)
            
        if np.random.rand() < acceptance_ratio:
            current_mu = proposed_mu
            current_log_post = proposed_log_post
            
        samples[i] = current_mu
        
    return samples

np.random.seed(42)
burn_in = 1000
iterations = 5000

print("="*95)
print(f"BÁO CÁO SENTIMENT (MÔ PHỎNG 1 NGÀY VỚI {len(all_scores)} TIN MỚI NHẤT)")
print("="*95)

print(f"{'Kênh / Composite':<25} | {'Số tin':<6} | {'PP Cũ (Trung bình)':<18} | {'PP MCMC (Bayes)':<18} | {'Xác suất Tích cực (>0)':<20}")
print("-" * 95)

# Xử lý MACRO COMPOSITE (Tất cả tin trong 1 ngày)
all_scores_np = np.array(all_scores)
composite_mean = np.mean(all_scores_np)
samples_comp = mcmc_sample(all_scores_np, iterations=iterations)[burn_in:]
bayesian_mean_comp = np.mean(samples_comp)
prob_pos_comp = np.mean(samples_comp > 0)

print(f"{'MACRO COMPOSITE (ALL)':<25} | {len(all_scores_np):<6} | {composite_mean:<18.4f} | {bayesian_mean_comp:<18.4f} | {prob_pos_comp:.2%}")
print("-" * 95)

# Xử lý cho từng kênh nhỏ (Channels)
for channel, scores in sorted(channels_raw_scores.items(), key=lambda x: len(x[1]), reverse=True):
    data_np = np.array(scores)
    curr_mean = np.mean(data_np)
    
    samples = mcmc_sample(data_np, iterations=iterations)[burn_in:]
    b_mean = np.mean(samples)
    p_pos = np.mean(samples > 0)
    
    print(f"{channel:<25} | {len(data_np):<6} | {curr_mean:<18.4f} | {b_mean:<18.4f} | {p_pos:.2%}")
    
print("="*95)
