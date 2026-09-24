"""离线验证登录、重订阅和行情输出，不连接柜台。"""

import contextlib
import io
import unittest
from unittest.mock import patch

from main import MarketApi, TraderApi, price


CONFIG = dict(userid="test", password="test", brokerid="9999", appid="test", auth_code="test", symbols=["rb2701", "ag2612"])


class DemoTests(unittest.TestCase):
    def test_market_login_and_resubscribe(self):
        api = MarketApi(CONFIG)
        with patch.object(MarketApi, "reqUserLogin", return_value=0) as login:
            api.onFrontConnected()
            self.assertEqual(login.call_args.args[0]["UserID"], "test")
        with patch.object(MarketApi, "subscribeMarketData", return_value=0) as subscribe:
            api.onRspUserLogin({}, {"ErrorID": 3}, 1, True)
            subscribe.assert_not_called()
            api.onRspUserLogin({}, {}, 2, True)
            self.assertEqual(subscribe.call_count, 2)
            api.onFrontDisconnected(1)
            self.assertFalse(api.logged_in)
            api.onRspUserLogin({}, {}, 3, True)
            self.assertEqual(subscribe.call_count, 4)

    def test_authentication_gates_trade_login(self):
        api = TraderApi(CONFIG)
        with patch.object(TraderApi, "reqUserLogin", return_value=0) as login:
            api.onRspAuthenticate({}, {"ErrorID": 63}, 1, True)
            login.assert_not_called()
            api.onRspAuthenticate({}, {}, 2, True)
            login.assert_called_once()

    def test_tick_print_and_invalid_price(self):
        api = MarketApi(CONFIG)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            api.onRtnDepthMarketData(dict(InstrumentID="rb2701", UpdateMillisec=5, LastPrice=3100))
        self.assertIn("TICK rb2701", output.getvalue())
        self.assertIn("最新=3100", output.getvalue())
        self.assertEqual(api.ticks, 1)
        self.assertEqual(price(float('inf')), "-")
        self.assertEqual(price(1.7976931348623157e308), "-")


if __name__ == "__main__":
    unittest.main()
