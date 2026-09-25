"""跳空寿命因子的最小可复用核心。"""
import numpy as np
import pandas as pd

def lag(x):
    return np.vstack([np.full((1,x.shape[1]),np.nan),x[:-1]])

def inputs(op, close, high, low, member):
    prev=lag(close)
    with np.errstate(divide='ignore',invalid='ignore'):
        gap=op/prev-1; ret=close/prev-1
        vol=pd.DataFrame(ret).rolling(20,min_periods=20).std().shift(1).to_numpy()
        direction=np.sign(gap); fill=np.where(direction>0,low<=prev,high>=prev)
        quality=(op>0)&(close>0)&(low>0)&(high>=np.maximum(op,close))&(low<=np.minimum(op,close))
        event=member&quality&np.isfinite(gap)&(np.abs(gap)>=.001)&(vol>1e-6)&~fill
        market=np.nanmean(np.where(member&np.isfinite(ret),ret,np.nan),axis=1)[:,None]
        clv=np.divide(2*close-high-low,high-low,out=np.zeros_like(close),where=high>low)
        x=np.stack([direction,np.abs(gap)/vol,direction*(close/prev-1)/vol,
                    direction*(close/op-1)/vol,(high-low)/prev/vol,clv*direction,
                    vol,np.broadcast_to(market,close.shape)],axis=2)
    return x,event,gap

def predict_hazards(model,x):
    low,high,scaler,clf=model
    return clf.predict_proba(scaler.transform(np.clip(x,low,high)))[:,1]
