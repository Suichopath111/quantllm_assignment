"""打印项目内已保存的历史结果。"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
for name in ['historical-summary.json']:
    print(f'--- {name} ---')
    print(json.dumps(json.loads((ROOT/'results'/name).read_text(encoding='utf8')),ensure_ascii=False,indent=2))
