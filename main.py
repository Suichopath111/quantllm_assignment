"""使用底层 CTP API 登录并持续打印行情，按 Ctrl+C 退出。"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event

from vnpy_ctp.api import MdApi, TdApi


ROOT = Path(__file__).resolve().parent


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def failed(error, action):
    if error and error.get("ErrorID", 0):
        log(f"{action}失败：{error.get('ErrorID')} {error.get('ErrorMsg', '')}")
        return True
    return False


def price(value):
    if value is None or not math.isfinite(value) or abs(value) > 1e100:
        return "-"
    return f"{value:g}"


class MarketApi(MdApi):
    """行情连接独立于交易登录，重连登录成功后重新订阅。"""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.reqid = 0
        self.logged_in = False
        self.ticks = 0
        self.last_tick = None
        self.strategy = None

    def onFrontConnected(self):
        log("MD 网络连接成功，发起行情登录")
        self.reqid += 1
        result = self.reqUserLogin({
            "UserID": self.config["userid"],
            "Password": self.config["password"],
            "BrokerID": self.config["brokerid"],
        }, self.reqid)
        if result:
            log(f"MD 登录请求未发出，返回码 {result}")

    def onRspUserLogin(self, data, error, reqid, last):
        if failed(error, "MD 登录"):
            return
        self.logged_in = True
        log(f"MD 登录成功，交易日 {data.get('TradingDay', '')}")
        for symbol in self.config["symbols"]:
            result = self.subscribeMarketData(symbol)
            log(f"订阅请求 {symbol}，返回码 {result}")

    def onRspSubMarketData(self, data, error, reqid, last):
        if not failed(error, "行情订阅"):
            log(f"订阅成功：{data.get('InstrumentID', '')}")

    def onRtnDepthMarketData(self, data):
        self.ticks += 1
        self.last_tick = time.monotonic()
        log(
            f"TICK {data.get('InstrumentID', '')} "
            f"交易日={data.get('TradingDay', '')} "
            f"自然日={data.get('ActionDay', '')} "
            f"{data.get('UpdateTime', '')}.{data.get('UpdateMillisec', 0):03d} "
            f"最新={price(data.get('LastPrice'))} "
            f"买一={price(data.get('BidPrice1'))}×{data.get('BidVolume1', 0)} "
            f"卖一={price(data.get('AskPrice1'))}×{data.get('AskVolume1', 0)} "
            f"累计量={data.get('Volume', 0)} 持仓={data.get('OpenInterest', 0)}"
        )
        if self.strategy:
            self.strategy.on_tick(data)

    def onFrontDisconnected(self, reason):
        self.logged_in = False
        log(f"MD 断线，原因 {reason}；等待底层 API 重连")

    def onRspError(self, error, reqid, last):
        failed(error, "MD 请求")


class TraderApi(TdApi):
    """只验证交易认证和登录，不包含下单操作。"""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.reqid = 0
        self.logged_in = False

    def onFrontConnected(self):
        log("TD 网络连接成功，发起客户端认证")
        self.reqid += 1
        result = self.reqAuthenticate({
            "UserID": self.config["userid"],
            "BrokerID": self.config["brokerid"],
            "AppID": self.config["appid"],
            "AuthCode": self.config["auth_code"],
        }, self.reqid)
        if result:
            log(f"TD 认证请求未发出，返回码 {result}")

    def onRspAuthenticate(self, data, error, reqid, last):
        if failed(error, "TD 认证"):
            return
        log("TD 认证成功，发起交易登录")
        self.reqid += 1
        result = self.reqUserLogin({
            "UserID": self.config["userid"],
            "Password": self.config["password"],
            "BrokerID": self.config["brokerid"],
        }, self.reqid)
        if result:
            log(f"TD 登录请求未发出，返回码 {result}")

    def onRspUserLogin(self, data, error, reqid, last):
        if failed(error, "TD 登录"):
            return
        self.logged_in = True
        log(f"TD 登录成功，交易日 {data.get('TradingDay', '')}")

    def onFrontDisconnected(self, reason):
        self.logged_in = False
        log(f"TD 断线，原因 {reason}；等待底层 API 重连")

    def onRspError(self, error, reqid, last):
        failed(error, "TD 请求")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.json")
    parser.add_argument("--symbols", nargs="+", help="覆盖订阅合约，例如 rb2701 ag2612 au2612")
    parser.add_argument("--duration", type=float, default=0, help="验证时限秒数；默认 0 表示持续运行")
    parser.add_argument("--trade-symbol", default="rb2701", help="触发交易的单个合约")
    parser.add_argument("--threshold", type=float, help="最新价严格大于该值时触发一次")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy", help="买入开仓或卖出开仓，固定1手")
    parser.add_argument("--enable-trading", action="store_true", help="启用向 SimNow 报单；默认只打印信号")
    args = parser.parse_args()
    if args.duration < 0:
        parser.error("duration 不能小于 0")
    if args.threshold is not None and (not math.isfinite(args.threshold) or args.threshold <= 0):
        parser.error("threshold 必须为有限正数")
    if args.enable_trading and args.threshold is None:
        parser.error("启用交易必须指定 --threshold")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        parser.error("配置读取失败，请按 config.example.json 创建 config.local.json")
    for key in ("userid", "password", "brokerid", "td_address", "md_address", "appid", "auth_code"):
        if not isinstance(config.get(key), str) or not config[key]:
            parser.error(f"配置缺少非空字符串字段：{key}")
    symbols = args.symbols or config.get("symbols")
    if not isinstance(symbols, list) or not symbols or not all(isinstance(s, str) and s.isalnum() for s in symbols):
        parser.error("symbols 必须是非空合约代码列表")
    config["symbols"] = list(dict.fromkeys(symbols))
    if args.threshold is not None and args.trade_symbol not in config["symbols"]:
        parser.error("交易合约必须包含在订阅 symbols 中")
    if args.enable_trading and (config['brokerid'] != '9999' or config['td_address'] != 'tcp://182.254.243.31:30001'):
        parser.error("本 Demo 下单仅允许 SimNow 第一套 30001 / BrokerID 9999")
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    # 原生 CTP 对中文绝对路径兼容性不稳定，使用运行目录内的 ASCII 相对路径。
    os.chdir(runtime)
    md, td = MarketApi(config), TraderApi(config)
    if args.threshold is not None:
        from trading import ThresholdTrader
        td = ThresholdTrader(config, args.trade_symbol, args.threshold, args.side,
                             args.enable_trading, runtime / "trade-once.json")
        md.strategy = td
        log(f"策略：{args.trade_symbol} 最新价 > {args.threshold}，{args.side}开仓1手；"
            f"模式={'SimNow报单' if args.enable_trading else '仅打印信号'}")
    started = []
    stop = Event()
    begin = time.monotonic()
    log(f"订阅合约：{', '.join(config['symbols'])}；按 Ctrl+C 退出")
    try:
        for api, name, address in ((md, "md", "md_address"), (td, "td", "td_address")):
            flow = f"{name}_flow/"
            Path(flow).mkdir(exist_ok=True)
            create = api.createFtdcMdApi if name == "md" else api.createFtdcTraderApi
            create(flow, config.get("production_mode", True))
            started.append(api)
            api.registerFront(config[address])
            api.init()
        next_status = begin + 15
        while not stop.wait(0.5):
            if md.strategy:
                td.poll()
            now = time.monotonic()
            if args.duration and now - begin >= args.duration:
                break
            if now >= next_status:
                age = "尚无行情" if md.last_tick is None else f"距上次行情 {now - md.last_tick:.0f} 秒"
                log(f"运行中：MD登录={md.logged_in} TD登录={td.logged_in} Tick数={md.ticks}；{age}")
                next_status = now + 15
    except KeyboardInterrupt:
        log("收到 Ctrl+C，关闭连接")
    finally:
        for api in reversed(started):
            api.exit()
        log(f"已退出，共收到 {md.ticks} 条行情")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
