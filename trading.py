"""单合约阈值策略：固定一手对手价限价开仓，不自动重试。"""

import json
import math
import time
from threading import RLock

from main import TraderApi, log, failed


class ThresholdTrader(TraderApi):
    """先串行查询柜台状态，再允许行情触发一次报单。"""

    def __init__(self, config, symbol, threshold, side, enabled, journal):
        super().__init__(config)
        self.symbol, self.threshold, self.side = symbol, threshold, side
        self.enabled, self.journal = enabled, journal
        self.lock = RLock()
        self.triggered = False
        self.ready = False
        self.pending = None
        self.due = 0
        self.instrument = None
        self.available = None
        self.blocked = False
        self.order_ref = 0
        self.trading_day = ''

    def schedule(self, name):
        self.pending = name
        self.due = time.monotonic() + 1.1

    def poll(self):
        with self.lock:
            if not self.logged_in or not self.pending or time.monotonic() < self.due:
                return
            name, self.pending = self.pending, None
            request = {'BrokerID': self.config['brokerid'], 'InvestorID': self.config['userid']}
            if name == 'Instrument':
                request = {'InstrumentID': self.symbol}
            self.reqid += 1
            result = getattr(self, 'reqQry' + name)(request, self.reqid)
            if result:
                log(f'查询{name}未发出：{result}；策略保持禁用，请重启检查')

    def onRspUserLogin(self, data, error, reqid, last):
        with self.lock:
            self.ready = False
            self.pending = None
            super().onRspUserLogin(data, error, reqid, last)
            if error and error.get('ErrorID'):
                return
            self.trading_day = data.get('TradingDay', '')
            self.order_ref = max(self.order_ref, int(data.get('MaxOrderRef', '').strip() or 0))
            self.instrument, self.available, self.blocked = None, None, False
            self.reqid += 1
            result = self.reqSettlementInfoConfirm({
                'BrokerID': self.config['brokerid'], 'InvestorID': self.config['userid']
            }, self.reqid)
            if result:
                log(f'结算确认请求未发出：{result}')

    def onRspSettlementInfoConfirm(self, data, error, reqid, last):
        with self.lock:
            if not failed(error, '结算确认') and last and self.logged_in:
                self.schedule('Instrument')

    def onRspQryInstrument(self, data, error, reqid, last):
        with self.lock:
            if failed(error, '合约查询'):
                self.blocked = True
            if data.get('InstrumentID') == self.symbol:
                self.instrument = data
            if last and not self.blocked and self.logged_in:
                self.schedule('TradingAccount')

    def onRspQryTradingAccount(self, data, error, reqid, last):
        with self.lock:
            if failed(error, '资金查询'):
                self.blocked = True
            if data.get('CurrencyID') == 'CNY':
                self.available = data.get('Available', 0)
                log(f'人民币可用资金：{self.available}')
            if last and not self.blocked and self.logged_in:
                self.schedule('InvestorPosition')

    def onRspQryInvestorPosition(self, data, error, reqid, last):
        with self.lock:
            if failed(error, '持仓查询'):
                self.blocked = True
            if data.get('InstrumentID') == self.symbol and data.get('Position', 0) > 0:
                self.blocked = True
                self.ready = False
                log('目标合约已有持仓，禁止自动开仓')
            if last and not self.blocked and self.logged_in:
                self.schedule('Order')

    def check_order(self, data):
        if data.get('InstrumentID') == self.symbol and data.get('OrderStatus') not in ('0', '2', '4', '5'):
            self.blocked = True
            self.ready = False
            log('目标合约存在活动或状态不明委托，禁止新开仓')

    def onRspQryOrder(self, data, error, reqid, last):
        with self.lock:
            if failed(error, '委托查询'):
                self.blocked = True
            self.check_order(data)
            if last:
                contract = self.instrument or {}
                tick = contract.get('PriceTick', 0)
                self.ready = bool(self.logged_in and not self.blocked and contract.get('IsTrading')
                    and contract.get('ExchangeID') and math.isfinite(tick) and tick > 0
                    and contract.get('MinLimitOrderVolume', 0) <= 1 <= contract.get('MaxLimitOrderVolume', 0)
                    and self.available is not None and math.isfinite(self.available) and self.available > 0)
                log(f'策略准备完成：允许触发={self.ready}；资金是否足够开仓由柜台最终校验')

    def onFrontDisconnected(self, reason):
        with self.lock:
            self.ready, self.pending = False, None
            super().onFrontDisconnected(reason)

    def on_tick(self, data):
        with self.lock:
            if not self.ready or not self.logged_in or self.triggered or data.get('InstrumentID') != self.symbol:
                return
            if data.get('TradingDay') != self.trading_day:
                return
            latest = data.get('LastPrice', 0)
            field = 'Ask' if self.side == 'buy' else 'Bid'
            limit = data.get(field + 'Price1', 0)
            if not all(isinstance(x, (int, float)) and math.isfinite(x) and 0 < x < 1e100 for x in (latest, limit)):
                return
            if latest <= self.threshold or data.get(field + 'Volume1', 0) <= 0:
                return
            tick = self.instrument['PriceTick']
            if not math.isclose(limit / tick, round(limit / tick), abs_tol=1e-6, rel_tol=0):
                return
            self.triggered = True
            log(f'触发：{self.symbol} 最新={latest} > {self.threshold}；{self.side}开仓1手 限价={limit}')
            if not self.enabled:
                log('仅打印信号，未发送订单')
                return
            self.order_ref += 1
            request = dict(InstrumentID=self.symbol, ExchangeID=self.instrument['ExchangeID'],
                BrokerID=self.config['brokerid'], InvestorID=self.config['userid'], UserID=self.config['userid'],
                OrderRef=str(self.order_ref), LimitPrice=limit, VolumeTotalOriginal=1,
                OrderPriceType='2', Direction='0' if self.side == 'buy' else '1',
                CombOffsetFlag='0', CombHedgeFlag='1', ContingentCondition='1',
                ForceCloseReason='0', IsAutoSuspend=0, TimeCondition='3', VolumeCondition='1', MinVolume=1)
            # 排他创建并先落盘：即使进程崩溃或重启，也不自动重复报单。
            try:
                with self.journal.open('x', encoding='utf-8') as stream:
                    json.dump({'symbol': self.symbol, 'order_ref': self.order_ref,
                               'limit': limit, 'side': self.side}, stream)
                    stream.flush()
                    import os
                    os.fsync(stream.fileno())
            except OSError as exc:
                log(f'禁止报单：一次性标记已存在或无法保存（{type(exc).__name__}）')
                return
            self.reqid += 1
            result = self.reqOrderInsert(request, self.reqid)
            log(f'报单请求返回={result}，OrderRef={self.order_ref}；不自动重试，等待委托/成交回报')

    def onRspOrderInsert(self, data, error, reqid, last):
        failed(error, '报单')

    def onErrRtnOrderInsert(self, data, error):
        failed(error, '异步报单')

    def onRtnOrder(self, data):
        with self.lock:
            self.check_order(data)
            log(f"委托 {data.get('InstrumentID')} Ref={data.get('OrderRef')} "
                f"状态={data.get('OrderStatus')} 已成交={data.get('VolumeTraded')} "
                f"剩余={data.get('VolumeTotal')} {data.get('StatusMsg', '')}")

    def onRtnTrade(self, data):
        with self.lock:
            if data.get('InstrumentID') == self.symbol:
                self.ready = False
            log(f"成交 {data.get('InstrumentID')} Ref={data.get('OrderRef')} "
                f"成交编号={data.get('TradeID')} 价格={data.get('Price')} 手数={data.get('Volume')}")
