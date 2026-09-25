"""因子核心的离线结构测试。"""
import numpy as np
from gap_survival import inputs

def test_gap_event_shape_and_no_future_input():
    n,m=40,4; close=np.full((n,m),100.); op=close.copy(); high=close+1; low=close-1
    op[20,0]=102.; member=np.ones((n,m),dtype=bool)
    x,event,gap=inputs(op,close,high,low,member)
    assert x.shape==(n,m,8); assert event.shape==(n,m); assert np.isfinite(gap[20,0])

def test_non_event_below_threshold():
    n,m=40,2; close=np.full((n,m),100.); op=close.copy(); high=close+1; low=close-1
    op[20,0]=100.05
    _,event,_=inputs(op,close,high,low,np.ones((n,m),dtype=bool))
    assert not event[20,0]
