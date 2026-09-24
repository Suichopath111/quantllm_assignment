"""唯一因子：三日跳空回补概率方向分数。"""
import numpy as np
import pandas as pd
from gap_survival import inputs, predict_hazards

def fill3_direction(op, close, high, low, member, frozen_model):
    """使用冻结模型计算 fill3_direction；输入均为日期×股票矩阵。"""
    features, event, _, _, gap, _ = inputs(op, close, high, low, member)
    idx, symbols = np.where(event), np.eye(3)
    probability = np.full(event.shape, np.nan)
    for h in range(3):
        if len(idx[0]) == 0:
            continue
        day = np.broadcast_to(symbols[h], (len(idx[0]), 3))
        hazard = predict_hazards(frozen_model, np.column_stack([features[idx], day]))
        probability[idx] = np.nan_to_num(probability[idx], nan=0.0) + hazard / 3.0
    return np.where(event, np.sign(gap) * (1.0 - 2.0 * probability), np.nan)
