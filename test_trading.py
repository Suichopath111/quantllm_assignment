"""离线检查策略门禁、报单字段与重复提交保护。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading import ThresholdTrader
from test_demo import CONFIG


class TradingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Path(self.temp.name) / 'once.json'
        self.api = self.make_api()
        self.tick = dict(InstrumentID='rb2701', TradingDay='20260921', LastPrice=3121,
                         AskPrice1=3122, AskVolume1=5, BidPrice1=3120, BidVolume1=4)

    def make_api(self, enabled=True, side='buy'):
        api = ThresholdTrader(CONFIG, 'rb2701', 3120, side, enabled, self.journal)
        api.logged_in = api.ready = True
        api.trading_day = '20260921'
        api.instrument = dict(PriceTick=1, ExchangeID='SHFE', IsTrading=1,
                              MinLimitOrderVolume=1, MaxLimitOrderVolume=500)
        return api

    def test_buy_once_and_restart(self):
        with patch.object(ThresholdTrader, 'reqOrderInsert', return_value=0) as send:
            self.api.on_tick(self.tick)
            self.api.on_tick(self.tick)
            self.make_api().on_tick(self.tick)
            send.assert_called_once()
            order = send.call_args.args[0]
            self.assertEqual((order['LimitPrice'], order['Direction'], order['VolumeTotalOriginal']), (3122, '0', 1))
            self.assertEqual((order['OrderPriceType'], order['CombOffsetFlag']), ('2', '0'))

    def test_dry_run_and_sell(self):
        with patch.object(ThresholdTrader, 'reqOrderInsert', return_value=0) as send:
            self.make_api(False).on_tick(self.tick)
            send.assert_not_called()
            self.assertFalse(self.journal.exists())
            self.make_api(side='sell').on_tick(self.tick)
            self.assertEqual(send.call_args.args[0]['LimitPrice'], 3120)
            self.assertEqual(send.call_args.args[0]['Direction'], '1')

    def test_invalid_ticks_and_not_ready(self):
        with patch.object(ThresholdTrader, 'reqOrderInsert') as send:
            for changes in ({'LastPrice': 3120}, {'AskPrice1': float('inf')},
                            {'AskVolume1': 0}, {'AskPrice1': 3122.5},
                            {'TradingDay': '20260918'}, {'InstrumentID': 'ag2612'}):
                self.api.on_tick(self.tick | changes)
            self.api.ready = False
            self.api.on_tick(self.tick)
            send.assert_not_called()

    def test_rejected_send_no_retry(self):
        with patch.object(ThresholdTrader, 'reqOrderInsert', return_value=-2) as send:
            self.api.on_tick(self.tick)
            self.api.onRspOrderInsert({}, {'ErrorID': 31}, 1, True)
            self.api.on_tick(self.tick)
            send.assert_called_once()

    def test_preparation_and_existing_position(self):
        api = self.make_api()
        api.available = 100000
        api.onRspQryOrder({}, {}, 1, True)
        self.assertTrue(api.ready)
        api.onRspQryInvestorPosition({'InstrumentID': 'rb2701', 'Position': 1}, {}, 2, True)
        api.onRspQryOrder({}, {}, 3, True)
        self.assertFalse(api.ready)
        api = self.make_api()
        api.onRtnOrder({'InstrumentID': 'rb2701', 'OrderStatus': '3'})
        self.assertFalse(api.ready)

    def test_disconnect_and_failed_query(self):
        self.api.onFrontDisconnected(1)
        self.assertFalse(self.api.ready)
        self.api.onRspQryOrder({}, {}, 1, True)
        self.assertFalse(self.api.ready)
        self.api.logged_in = True
        self.api.available = 100000
        self.api.onRspQryOrder({}, {'ErrorID': 1}, 2, True)
        self.assertFalse(self.api.ready)


if __name__ == '__main__':
    unittest.main()
