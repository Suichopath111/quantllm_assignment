# CTP SimNow 最小行情与阈值交易 Demo

基于 `vnpy_ctp.api.MdApi` 和 `TdApi` 的行情与交易demo：处理底层回调，完成交易认证、行情订阅、Tick 打印及可选的一次性阈值开仓。

```text
ctp-simnow-demo/
├── main.py              # 连接、登录、订阅、行情输出与命令行入口
├── trading.py           # 柜台状态查询、阈值开仓与委托成交回报
├── config.example.json  # 配置模板
├── requirements.txt     # 依赖版本
├── test_demo.py         # 行情与登录离线测试
├── test_trading.py      # 阈值策略与防重复报单离线测试
└── README.md
```

## 安装与配置

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

编辑 `config.json`。默认连接交易端口 30001、行情端口 30011。如需夜盘需修改端口

`production_mode=true` 表示原生 API 的接口库模式

## 持续行情

```powershell
python -X utf8 main.py
```

默认订阅 `rb2701`、`ag2612`、`au2612`，逐条打印最新价、买卖一档、累计成交量和持仓量；每15秒输出登录状态及 Tick 数量。行情断线重连、重新登录成功后会重新订阅。

合约为示例候选，使用时应按当前可交易月份修改：

```powershell
python -X utf8 main.py --symbols rb2701 ag2612 au2612
python -X utf8 main.py --duration 30
```

`--duration` 仅用于限时观察，默认0表示持续运行。

## 阈值策略

先观察信号，3120仅为演示阈值：

```powershell
python -X utf8 main.py --trade-symbol rb2701 --threshold 3120
```

策略在结算确认后，以至少1.1秒的间隔串行查询合约、人民币资金、持仓和委托。准备完成且最新价**严格大于阈值**时触发一次；启动时价格已经高于阈值也会触发。

交易合约必须包含在订阅列表中。默认买入开仓1手，买价取卖一；`--side sell` 为卖出开仓1手，卖价取买一。卖出方向也使用“最新价大于阈值”的触发条件。

添加 `--enable-trading` 才会向 SimNow 报单，订单为普通当日有效限价单：

```powershell
python -X utf8 main.py --trade-symbol rb2701 --threshold 3120 --enable-trading
```

## 课件因子研究

目录 `gap-survival-factor/` 收录了按照课程课件要求挖掘的股票跳空寿命方向因子 `fill3_direction`。它完成了跳空事件定义、回补标签、滚动 Logistic 风险模型、训练/验证/历史复验切分，以及基于该因子的历史组合研究。

该因子属于股票研究模块，与本目录的 CTP/SimNow 期货行情和阈值交易 Demo 分开；当前没有把股票因子直接接入期货下单。研究结果仅作课程学习与研究记录，README 中已披露其收益稳定性和数据限制。

## 其他

- 目标合约已有持仓或活动/状态不明委托时，阻止新开仓；查询失败时保持禁用。
- 可用资金只检查为正，未校验保证金要求。
- 原生流文件与一次性标记保存在自动生成的 `.runtime/`

---

原开发环境于2026-09-21验证过 SimNow 登录及三个合约行情订阅，30秒收到137条 Tick。阈值交易代码仅完成离线验证，尚未实际报单验证成交。
