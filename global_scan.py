#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日全球重大事件与资金流向深度扫描 (GitHub Action 版)
================================================
- 每天 09:00（北京时间）由 GitHub Action 定时触发
- 使用智谱 GLM-4-Flash（免费 + 内置 web_search 实时联网检索）执行「全球重大事件深度扫描」提示词
- 报告最前面强制输出：影响【今日】与【明日】走势的因子清单，逐条标注已确认 / 未确认状态
- 输出落盘 global_scan/YYYY-MM-DD.md
- iPhone 15 Pro 友好 HTML 排版推送微信 (PushPlus)

依赖：仅标准库（urllib / json），无需第三方包
环境变量：
  [智谱 GLM-4-Flash，推荐，免费且实时联网]
  ZHIPU_API_KEY     (必填，智谱 API Key)
  ZHIPU_MODEL       (选填，默认 glm-4-flash)
  ZHIPU_BASE_URL    (选填，默认 https://open.bigmodel.cn/api/paas/v4)
  [Gemini 兜底]
  GEMINI_API_KEY / GEMINI_API_KEYS / GEMINI_MODEL / GEMINI_BASE_URL (选填)
  [推送]
  PUSHPLUS_TOKEN    (选填，填了就推微信；不填则只落盘)
  PUSHPLUS_TOPIC    (选填，一对多群组编码；填了则推给整个群组)
"""

import os
import re
import sys
import json
import time
import datetime
import urllib.request
import urllib.error

# ---------- 配置 ----------
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
_KEYS_RAW = (os.environ.get("GEMINI_API_KEYS") or "").strip()
GEMINI_KEYS_LIST = [k.strip() for k in _KEYS_RAW.split(",") if k.strip()] if _KEYS_RAW else []
if not GEMINI_KEY and GEMINI_KEYS_LIST:
    GEMINI_KEY = GEMINI_KEYS_LIST[0]

PUSHPLUS_TOKEN = (os.environ.get("PUSHPLUS_TOKEN") or "").strip()
PUSHPLUS_TOPIC = (os.environ.get("PUSHPLUS_TOPIC") or "").strip()
MODEL = (os.environ.get("GEMINI_MODEL") or "gemini-3-flash-preview").strip()
GEMINI_BASE_URL = (os.environ.get("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/")

ZHIPU_KEY = (os.environ.get("ZHIPU_API_KEY") or "").strip()
ZHIPU_MODEL = (os.environ.get("ZHIPU_MODEL") or "glm-4-flash").strip()
ZHIPU_BASE_URL = (os.environ.get("ZHIPU_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4").strip().rstrip("/")

# 深度分析优先用 Gemini（免费额度大 + Google 搜索原生集成；GitHub Models 已于 2026-07-30 退役，不再使用）

GEN_DATE = datetime.date.today().strftime("%Y-%m-%d")
GEN_DATETIME_CN = datetime.datetime.now().strftime("%Y-%m-%d %H:%M") + "（北京时间）"
NEXT_DATE = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

# ---------- 扫描提示词核心（用户提供：全球重大事件与资金流向深度扫描·防遗漏增强版） ----------
PROMPT_CORE = """
## 一、你的角色

你是一支由以下人员组成的全球宏观与产业投资研究团队：

- 全球宏观经济分析师
- 美联储与全球央行政策研究员
- 全球股票、债券、外汇、大宗商品交易员
- 国际政治与地缘冲突分析师
- 全球科技产业与人工智能产业链研究员
- IPO、并购、融资及资本市场事件研究员
- A股行业轮动与机构资金行为研究员
- 新闻情报检索与信息交叉核验研究员

你的任务不是简单汇总新闻，而是从全球范围内主动寻找未来1—2周可能引起大规模资金重新配置、改变市场预期、影响主要资产价格或引发A股行业轮动的重大事件。

必须使用联网检索，优先检索最新公开信息，交叉核验关键消息，并给出来源、时间、证据等级、影响路径、可能影响的资金规模及验证条件。

## 二、本次扫描参数

重点预测窗口：
- 未来1—3个自然日（最高优先级：今天与明天）
- 未来4—7个自然日
- 未来8—14个自然日

扩展观察窗口：
- 未来15—30天内已经明确安排、但可能提前影响资金定价的重大事件。

地域覆盖：
- 美国、中国大陆、中国香港、欧盟、英国、日本、韩国、印度
- 中东、俄罗斯、乌克兰、巴西及其他重要资源出口国
- 其他可能影响全球金融市场的国家和地区。

资产覆盖：
- 全球股票、债券、利率、汇率、黄金、原油、天然气、铜、铝、稀土、农产品、航运、加密资产及相关衍生品。
- 特别关注美股大型科技股、AI产业链、全球半导体、云计算、数据中心、能源基础设施及中国A股映射。

## 三、最高优先级任务：先建立事件全景，不准只搜常规日历

必须把以下事件类别逐一检索。每类都要明确写出“发现了什么”或“本轮未发现经过核实的重大事件”，不得因为新闻热度低就直接跳过。

### A类：全球宏观与央行政策

1. 美联储议息会议、会议纪要、官员讲话、利率路径变化。
2. 美国CPI、PCE、非农就业、失业率、GDP、零售销售、ISM、国债拍卖。
3. 中国GDP、CPI、PPI、PMI、社融、信贷、财政政策、货币政策。
4. 欧洲央行、英国央行、日本央行及其他重要央行会议和政策变化。
5. 美国财政部发债计划、国债供给、债务上限、财政预算和政府停摆风险。
6. 美元流动性、日元套息交易、人民币汇率、跨境资金及全球融资条件。
7. 重要经济数据的发布时间、市场一致预期、前值、可能的意外方向。

必须分析数据超预期、符合预期、不及预期三种情景分别会如何影响利率、汇率、股票和大宗商品。

### B类：人工智能与全球科技资本开支——重点防遗漏

必须专门设置独立检索环节，不得只依赖宏观经济日历。

重点覆盖：

1. OpenAI、Anthropic、Google/Alphabet、Microsoft、Meta、Amazon、NVIDIA、AMD、Oracle、xAI、CoreWeave及其他重要AI企业。
2. AI公司IPO、上市申请、保密提交、公开提交S-1、招股书披露、路演、定价、挂牌计划、估值变化、融资和股权出售。
3. AI公司的收入、订单、客户合同、算力采购、云服务协议、数据中心建设、资本开支、现金流、融资需求及盈利能力。
4. 大型科技公司季度财报、业绩预告、业绩电话会、分析师会议及资本开支指引。
5. AI模型发布、重大性能突破、价格调整、商业化产品发布、企业客户大规模部署。
6. GPU、HBM、先进封装、光模块、交换机、PCB、服务器、液冷、数据中心电力设备、储能及电网建设。
7. AI企业与云厂商、芯片企业、电信运营商、能源企业之间的重大合同、合作、投资、收购和战略调整。
8. 监管机构对AI、芯片出口、反垄断、数据安全和大型科技企业的调查或新规。

必须主动搜索类似以下问题：

- 哪些大型AI公司可能在未来两周提交IPO申请或披露上市计划？
- 哪些企业可能在近期发布重大融资、财报、产品或客户合同消息？
- 是否存在媒体提前报道、匿名消息人士透露、公司尚未正式确认的重大事件？
- 是否有已经发生但还没有进入主流财经日历的事件？
- 哪些AI企业的财务披露可能改变市场对整个AI产业链盈利能力的判断？

检索关键词不能只用“AI新闻”，还要组合搜索：“IPO filing”“S-1”“confidential filing”“public filing”“listing plans”“pre-IPO”“fundraising”“capital expenditure”“earnings guidance”“data center contracts”“AI infrastructure”“investment plans”等关键词及对应的中文表达。

对可能存在的IPO事件，必须区分：
- 公司正式公告
- 监管文件或交易所文件
- 权威媒体援引知情人士的报道
- 其他媒体转载
- 市场传闻

如果报道说“最快本周五提交”，必须将它列入对应日期的事件清单，标注“预计发生、尚未确认”，而不能因为它尚未成为正式公告就遗漏。

### C类：全球IPO、并购、融资与资本市场事件

1. 大型科技企业、独角兽、AI企业、芯片企业及战略性企业IPO。
2. 重要IPO申报、招股书更新、发行定价、挂牌日期及上市推迟。
3. 大型并购、私有化、资产出售、分拆上市、战略投资。
4. 大额可转债、增发、债券发行、融资计划、债务重组及违约风险。
5. 重要企业破产、流动性危机、评级下调或融资渠道关闭。
6. 重要股东减持、锁定期解禁、监管处罚和财务造假事件。

IPO专项要求：
- 不能只查已经正式确定上市日期的公司。
- 必须搜索“正在准备上市”“计划提交文件”“保密递交”“最快某日提交”等早期信息。
- 必须关注发行规模、潜在估值、融资需求、可比公司估值和对同行业公司的资金分流或估值传导。
- 必须区分“上市申请”“通过审核”“开始路演”“定价”和“正式挂牌”这几个阶段。

### D类：国际政治、战争与地缘冲突

1. 美国与伊朗关系、军事行动、谈判、停火、制裁及核问题。
2. 霍尔木兹海峡、红海、苏伊士运河、黑海等重要航道的通行安全。
3. 俄乌战争、欧洲安全局势、能源设施受损、停火谈判。
4. 中美关系、贸易谈判、关税、出口管制、实体清单和科技限制。
5. 台海及东亚安全风险。
6. 中东产油国、OPEC+、俄罗斯等对石油供应的政策变化。
7. 重要国家选举、政府更迭、财政政策及可能改变贸易或能源政策的政治事件。

必须追踪事件是否出现升级、降级、谈判突破、制裁落地、航运中断或军事行动等状态变化。

不能只引用单一交战方的说法。重大军事消息要区分官方声明、独立核实报道和未经证实的社交媒体信息。

### E类：全球产业政策与监管事件

1. 美国政府、商务部、财政部、能源部、国防部、SEC、FTC及其他重要机构的新规。
2. 中国国务院、发改委、财政部、工信部、商务部、央行、证监会及地方政府政策。
3. 欧盟委员会、英国、日本、韩国和印度的产业补贴、贸易限制及监管措施。
4. 半导体出口管制、关税调整、反倾销调查、产业补贴和本地化要求。
5. AI监管、药品审批、医疗支付政策、汽车安全标准、能源与环保法规。
6. 政府采购、重大基础设施投资、财政预算及行业扶持计划。

必须优先检查官方原始文件，不能只使用媒体对政策的二手解读。

### F类：全球能源、资源与供应链

1. 原油、天然气、LNG、煤炭、成品油价格和供应变化。
2. OPEC+会议、产量调整、战略储备释放、制裁和供应中断。
3. 铜、铝、锂、镍、钴、稀土、钨、锡及其他战略矿产的供需、库存、出口限制和价格变化。
4. 半导体材料、电子布、铜箔、玻纤、PCB原料、化工原料涨价或停产。
5. 全球港口、航运、集装箱、空运和关键物流线路变化。
6. 极端天气、洪水、干旱、飓风、寒潮及对能源、农业和工业供应的影响。
7. 重要矿山、工厂、炼厂、芯片厂和数据中心的停产、事故、扩产或投产。

必须判断涨价究竟来自真实供需变化、短期炒作还是成本传导，并评估上下游利润如何重新分配。

### G类：全球重要企业财报与产业会议

1. 未来14天全球主要公司财报日历。
2. 大型科技、半导体、云计算、汽车、能源、金融、消费、医药公司业绩。
3. 重要行业大会、产品发布会、投资者日、分析师会议。
4. 重要汽车展、航空航天展、军工展、能源会议、医疗与生物科技会议。
5. 重要临床试验结果、药物审批、专利诉讼和重大技术发布。

不能只写会议名称。必须说明是否可能出现订单、政策、业绩、产品或资本开支方面的实质信息。

### H类：金融市场结构与潜在系统性风险

1. 重要基金赎回、杠杆交易、融资压力和流动性问题。
2. 大型金融机构、对冲基金、私人信贷、商业地产及影子银行风险。
3. 重要主权债券、信用债、银行和非银金融风险。
4. 美股集中度、期权到期、重要指数调整和被动资金再平衡。
5. 加密资产重大清算、稳定币风险和相关金融监管事件。
6. 全球市场异常波动、熔断、交易所规则变化。

重点区分“新闻热度高”和“潜在强制资金流量大”。优先关注可能引发被动调仓、保证金压力、风险平价策略调整或跨资产去杠杆的事件。

## 四、必须使用多渠道搜索，不能依赖单一搜索结果

至少覆盖以下信息源：

### 第一层：官方原始来源
- 美联储、美国劳工统计局、美国经济分析局、美国财政部、SEC、白宫。
- 中国国务院、发改委、财政部、工信部、商务部、央行、证监会、交易所。
- 欧央行、英国央行、日本央行、欧盟委员会。
- 企业投资者关系网站、财报、新闻稿、监管文件。
- 主要交易所、IPO申报数据库和政府公告。

### 第二层：国际主流财经媒体
- Reuters、Bloomberg、Financial Times、Wall Street Journal、CNBC、AP等。
- 重大事件优先使用至少两个独立可信来源交叉核验。
- 对匿名消息、未确认的IPO计划和突发事件，尽量找到最早的原创报道，不要只引用转载稿。

### 第三层：专业行业媒体
- 半导体、AI、能源、航运、矿业、汽车、医药和资本市场专业媒体。
- 用于发现主流媒体和宏观日历可能尚未收录的产业事件。

### 第四层：市场预期与价格验证
- 主要股指期货、国债收益率、美元指数、原油、黄金、铜、波动率指标。
- 公司股价、行业指数、成交量和资金变化。
- 对关键市场数据注明数据时间、市场时区和来源。

每一类重大事件都要进行至少一轮主动检索。不能因为第一轮搜索没发现，就认定没有事件。

## 五、必须执行“反向查漏审计”

第一轮事件清单完成后，不得立即生成最终报告。必须进行第二轮专门查漏，至少包括：

1. 检查未来14天是否有大型AI企业IPO申报、融资、财报或资本开支消息。
2. 检查全球前十大科技公司及重要AI初创企业是否有近期公告、财报或重大传闻。
3. 检查未来两周主要央行会议和重要经济数据是否有遗漏。
4. 检查未来两周是否有可能影响原油、天然气、航运和黄金的地缘政治事件。
5. 检查重大产业会议、政策听证会、监管截止日期、法院裁决和产品发布。
6. 搜索“可能在未来几天宣布”“最快周五”“知情人士称”“正在准备”“预计提交”“尚未正式宣布”等提前信号。
7. 比较官方日历、企业公告、媒体报道和专业行业消息，找出只存在于某一个信息源中的潜在重要事件。
8. 检查日期跨时区问题，避免将美国当地日期误当成北京时间日期。
9. 搜索近期已经发生、但可能在未来1—2周继续影响市场的事件，不要只看未来新发生的事情。
10. 对搜索结果中的转述和转载去重，追溯原始来源。

最终报告必须增加“查漏审计结果”部分，明确列出完成了哪些检查、哪些来源无法访问、哪些事件仍可能遗漏。

## 六、事件必须分级，且区分事实与预期

每条事件必须标记以下状态之一：

- 【已确认】：官方日历、公告、监管文件或已发生事实证实。
- 【高可信预期】：多家可靠媒体报道或明确市场日程支持，但尚未正式确认。
- 【单一来源消息】：只有一个可信度有限的来源，仍需继续核实。
- 【市场传闻】：未经可靠来源证实，不可作为确定事实。
- 【情景推演】：假设事件发生后，分析其可能产生的影响。

每条事件同时标注：
- 原始发布时间
- 事件发生时间
- 所属时区
- 换算后的北京时间
- 预计发生日期或时间窗口
- 信息来源及原始链接
- 是否已经被市场提前交易
- 下一步核实节点

不得把媒体预测写成公司公告，不得把市场预期写成已发生事实。

## 七、建立全球资金影响评分模型

每个事件按照100分制进行评估：

1. 潜在影响资金规模：25分。
2. 对利率、美元、全球流动性的影响：20分。
3. 对全球股票和大宗商品定价的影响：15分。
4. 对A股行业和个股的传导能力：15分。
5. 时间紧迫性和意外程度：10分。
6. 信息可信度：10分。
7. 市场尚未充分定价的程度：5分。

请注意：
- 这是研究优先级评分，不是事件发生概率，也不是收益率预测。
- 信息可信度低的事件不能仅因潜在影响巨大就获得高确定性评级。
- 对潜在影响巨大但尚未确认的事件，单独列为“高影响、低确定性监控清单”。

## 八、必须估算资金影响，但严禁伪造数字

每个重点事件要分析：

1. 可能直接影响的全球资产规模或相关市场规模。
2. 可能影响的行业市值范围。
3. 可能触发主动基金、被动指数资金、对冲基金、商品交易资金和散户资金中的哪一类。
4. 可能的资金流入方向、流出方向及传导时间。
5. 影响是短期交易性、阶段性配置，还是长期资本开支变化。

如果没有可靠的资金规模数据：
- 必须明确写“无法可靠量化”。
- 可以给出定性等级，或注明假设条件的情景区间。
- 不得编造某个事件将给A股带来几百亿元资金流入的结论。
- 必须区分“相关资产市值”“潜在成交规模”“实际净流入资金”，三者不能混用。

## 九、每个重大事件必须做三情景推演

对最重要的事件，至少给出：

- 基准情景：事件按当前预期发展。
- 超预期情景：事件出现更强的利好或更严重的风险。
- 低于预期情景：事件推迟、落空或产生负面意外。

每种情景都要写明：
1. 触发条件。
2. 首先反应的资产。
3. 可能受益的行业。
4. 可能受损的行业。
5. 对A股的传导路径。
6. 哪些市场信号可以验证判断。
7. 哪些信号出现后应推翻原判断。

## 十、A股映射要求

把全球事件转化成可验证的A股观察方向，不要只给概念名称。

对每个重点方向分析：
- 直接受益、间接受益、成本受损或估值受压的区别。
- 产业链的具体传导路径。
- A股上市公司的真实产品、客户、订单和收入相关性。
- 是否已有明显上涨、成交额放大、融资拥挤或主力资金集中。
- 未来1—5个交易日、1—2周、2—8周的潜在影响窗口。
- 是否存在低位、业绩改善、估值合理但尚未充分交易的候选股。
- 相关逻辑的失效条件。

不能仅凭概念标签把公司认定为受益者。没有客户、订单或财务证据时，要明确标注为间接受益或纯主题关联。

## 十一、最终报告格式（必须逐字遵守，这是评分的唯一依据）

整份报告使用中文，总字数不少于 3000 字。每个因子、每个事件必须有：**具体数字**（点位/百分比/金额/日期）、**明确的方向判断**（三选一，绝不并排罗列）、**可点击的真实来源链接**。宁可少写几条因子，也绝不写没有数字的空泛条目。

### 第一部分：隔夜与盘前关键数据（Markdown 表格）
先用联网搜索逐项查询以下 10 个指标的「最近一次收盘/最新报价」（检索关键词示例：「道琼斯指数 昨日收盘」「恒生指数 夜盘期货」「10年期美债收益率 最新」等），再用表格输出（每格必须有具体数字）：

| 指标 | 最新值 | 涨跌幅 | 数据时间（注明时区） |
|---|---|---|---|

必须包含这 10 行：道琼斯指数、纳斯达克指数、标普500、10年期美债收益率、美元指数、离岸人民币兑美元、布伦特原油、COMEX黄金、富时中国A50期货、恒生指数夜期。
**任何一格留空或写「暂无」= 整份报告不合格，必须重查重写。**

### 第二部分：影响【今日】走势的因子（6—10条，按重要性排序）
### 第三部分：影响【明日】走势的因子（6—10条，按重要性排序）

每个因子的格式必须严格执行下面的多行卡片（禁止合并成一行、禁止把选项罗列出来）：

```
### N.【状态】因子标题（标题里必须含核心数字或具体事件名）
- **数据支撑**：至少 2 个具体数字（当前值/预期值/前值/涉及金额/具体日期），注明出处
- **方向判断**：三选一，只能写其中一个词——偏多 / 偏空 / 中性；再用一句话说清「为什么影响今天或明天」
- **A股传导路径**：具体到板块或代表性公司（写明行业名或公司名），资金从哪里流出、流向哪里
- **验证信号**：出现什么现象说明判断成立；出现什么现象必须推翻判断（各写一条，要可观察、有数字）
- **来源**：[标题](真实URL) 至少 1 条可点击链接
```

状态四选一：【已确认】【高可信预期】【单一来源消息】【市场传闻】。已确认的因子排在未确认前面。禁止把媒体预测标注为已确认。

格式示例（**仅演示格式。输出时必须把每个「」占位符替换为本次联网检索到的真实数字与链接；正文中禁止出现任何「」占位符残留，禁止照抄本示例中的任何字句**）：

### 1.【状态】「事件标题：必须包含核心数字或具体事件名」
- **数据支撑**：「数字1」（预期「数字2」，前值「数字3」）；「数字4」（「发布时间+时区」）
- **方向判断**：偏多 ——「一句话：为什么影响今天或明天的行情」
- **A股传导路径**：「资金从哪里流出 → 流向哪些具体板块/代表性公司」
- **验证信号**：「可观察信号A出现则判断成立」；「可观察信号B出现则判断作废」
- **来源**：[「页面标题」](「直达具体文章/公告的URL」)

硬性禁令：
1. 输出中禁止出现 ``` 代码围栏（示例用「」占位，正文用真实数据，全程无需围栏）。
2. 来源链接必须直达具体文章/公告/数据页面，禁止给网站首页（如 xxx.gov.cn 根路径）当链接；实在找不到直达页就写明机构名与页面标题，不要伪造链接。
3. 所有事件与数字必须来自本次联网检索结果；检索不到的事件宁可不写，禁止编造。输出中所有日期必须与「今天/明天/未来两周」一致，禁止出现与当前日期矛盾的日期。
4. 事件日历的评分必须按真实重要性区分（如 90/75/60/45），禁止全部相同；无法确认具体日期的事件标注「日期待定」。

### 第四部分：未来14天重要事件日历（精选 8—15 条，Markdown 表格）
| 北京时间 | 事件 | 状态 | 方向（偏多/偏空/中性，三选一） | 评分(0-100) |
|---|---|---|---|---|

### 第五部分：高影响但低确定性事件（0—5条）
每条写明：事件是什么、目前有哪些证据、需要监控什么条件、下一次核实的时间点。

### 第六部分：本轮最容易被忽略的三个事件
分别回答：是什么、为什么容易漏掉、接下来如何验证。

### 输出前自检（逐项确认，不达标就重写该条）
1. 每个因子是否都包含 ≥2 个具体数字？
2. 所有「方向判断」是否都是三选一的单一结论？（报告中绝不允许出现「利多/利空/中性」「偏多/偏空/中性」这种并排罗列）
3. 每个因子是否都附了直达具体页面的真实来源链接（不是首页）？
4. 已确认与未确认是否严格区分？
5. 隔夜数据表格 10 行是否全部填了具体数字？
6. 正文是否还残留「」占位符、``` 围栏、或示例中的字句（如「非农新增12.0万人」）？有则必须全部替换为真实检索数据。
7. 报告中所有日期是否与今天/明天/未来两周一致？

## 十二、执行纪律

1. 先检索，后判断；不得凭记忆生成未来事件日历。
2. 所有日期以实际执行时的最新资料为准，先获取当前日期和时间。
3. 重大事实必须给出可点击来源，优先引用原始公告。
4. 关键事件尽量交叉核验至少两个独立来源。
5. 不得把“没有搜到”写成“没有发生”。
6. 对未确认消息必须保留不确定性，不得为了完整性而编造。
7. 不得只扫描常规经济日历；IPO、融资、重大合同、突发监管、地缘政治和提前披露的匿名消息同样重要。
8. 不得因事件发生时间不确定就遗漏；应列入监控清单并说明不确定性。
9. 不得将全球市场总成交额、市值或潜在资金暴露直接当作实际净流入资金。
10. 如果本轮时间不足或来源访问失败，必须明确披露扫描范围和限制，不能声称完成了全面扫描。
11. 报告最后必须回答：本轮最可能被忽略的三个重大事件是什么？为什么容易漏掉？接下来如何验证？
12. 请立即开始联网检索并完成扫描，不要只复述方法。
"""


# ---------- 聚焦分段调用：小模型单次任务越聚焦，产出越真实（第3轮调优） ----------

STATUS_RULES = (
    "状态标注四选一：【已确认】官方公告/监管文件/已发生事实；【高可信预期】多家可靠媒体报道或明确日程；"
    "【单一来源消息】仅一个来源待核实；【市场传闻】未经证实。禁止把媒体预测标成已确认。"
)

HARD_RULES = (
    "硬性禁令：\n"
    "1. 方向判断只能写「偏多」「偏空」「中性」三者之一，禁止罗列多个选项。\n"
    "2. 每个因子必须包含至少 2 个具体数字（当前值/预期值/前值/金额/日期）。\n"
    "3. 来源链接必须直达具体文章/公告/数据页面，禁止用网站首页冒充。\n"
    "4. 全文禁止出现 ``` 代码围栏。\n"
    "5. 所有事件与数字必须来自本次联网检索；检索不到的事件宁可不写，禁止编造。\n"
    "6. 所有日期必须与今天/明天/未来两周一致，禁止出现矛盾日期。"
)

CARD_TEMPLATE = (
    "每个因子严格按照以下多行卡片输出（「」为占位符，输出时必须替换为检索到的真实内容，禁止残留占位符）：\n"
    "### 1.【已确认】「事件标题：必须包含核心数字或具体事件名」\n"
    "- **数据支撑**：「数字1」（预期「数字2」，前值「数字3」）；「数字4」（「发布时间+时区」）\n"
    "- **方向判断**：偏多 ——「一句话：为什么影响今天或明天的行情」\n"
    "- **A股传导路径**：「资金从哪里流出 → 流向哪些具体板块/代表性公司」\n"
    "- **验证信号**：「信号A出现则判断成立」；「信号B出现则判断作废」\n"
    "- **来源**：[「页面标题」](「直达具体文章/公告的URL」)"
)

SEARCH_CHECKLIST = (
    "检索方向清单（每类至少检索一轮）：A.宏观与央行（美联储/中国经济数据与政策）；"
    "B.AI与科技资本开支（OpenAI/英伟达/国内算力链/AI公司IPO）；C.IPO并购融资；"
    "D.地缘冲突（俄乌/中东/中美关税）；E.产业政策监管；F.能源资源供应链（原油/稀土/航运）；"
    "G.重要财报与产业会议；H.市场结构与资金面（北向资金/两融/汇率）。"
)

def build_overnight_prompt() -> str:
    return (
        f"现在是 {GEN_DATETIME_CN}。你是财经数据助手。请用联网搜索逐项查询以下 10 个指标"
        "「最近一次收盘/最新报价」（可多次检索，关键词示例：「道琼斯指数 昨日收盘」「10年期美债收益率 最新」"
        "「离岸人民币 最新」「A50期货 夜盘」等），然后以 Markdown 表格输出，列：指标 | 最新值 | 涨跌幅 | 数据时间（注明时区）。\n"
        "10 项指标：道琼斯指数、纳斯达克指数、标普500、10年期美债收益率、美元指数、离岸人民币兑美元、"
        "布伦特原油、COMEX黄金、富时中国A50期货、恒生指数夜期。\n"
        "要求：能检索到几项就填几项，全部要有真实数字；个别指标实在检索不到就在「最新值」写「未检索到」，"
        "禁止编造数字；只输出表格本身，不要输出任何其他文字。"
    )

def build_today_prompt(overnight_md: str) -> str:
    return (
        f"现在是 {GEN_DATETIME_CN}，明天是 {NEXT_DATE}，此刻是 A 股开盘前。"
        "你是全球宏观与 A 股策略研究团队（宏观分析师/央行研究员/交易员/地缘分析师/AI产业链研究员/A股资金行为研究员）。\n"
        f"{SEARCH_CHECKLIST}\n"
        f"{STATUS_RULES}\n"
        f"{CARD_TEMPLATE}\n"
        f"{HARD_RULES}\n\n"
        "以下是刚检索到的隔夜与盘前数据，可直接引用其中的数字：\n\n"
        f"{overnight_md}\n\n"
        f"任务：联网检索「昨天 A 股收盘后到此刻」发生的、会影响**今天（{GEN_DATE}）A 股走势**的事件与数据"
        "（隔夜市场联动、政策、宏观数据、公司公告、地缘、AI产业链等），输出 6—10 个因子卡片。"
        "已确认因子排前面，按重要性排序。只输出因子卡片本身，不要输出其他章节或前言。"
    )

def build_nextday_prompt(overnight_md: str) -> str:
    return (
        f"现在是 {GEN_DATETIME_CN}，明天是 {NEXT_DATE}。"
        "你是全球宏观与 A 股策略研究团队（宏观分析师/央行研究员/交易员/地缘分析师/AI产业链研究员）。\n"
        f"{SEARCH_CHECKLIST}\n"
        f"{STATUS_RULES}\n"
        f"{CARD_TEMPLATE}\n"
        f"{HARD_RULES}\n\n"
        "以下是隔夜与盘前数据，可参考其中的数字：\n\n"
        f"{overnight_md}\n\n"
        f"任务：联网检索未来 1—14 天已排期或大概率发生的事件（央行会议、经济数据发布、财报、IPO、"
        "产业会议、监管节点、地缘事件），依次输出以下四个部分：\n\n"
        f"## 影响【明日（{NEXT_DATE}）】走势的因子\n"
        "6—10 个因子卡片，格式同上。\n\n"
        "## 未来14天重要事件日历\n"
        "Markdown 表格（列：北京时间 | 事件 | 状态 | 方向 | 评分(0-100)），8—15 条；"
        "评分必须按真实重要性区分（如 90/75/60/45），禁止全部相同；日期不确定的标注「日期待定」。\n\n"
        "## 高影响但低确定性事件\n"
        "0—5 条，每条写明：事件是什么/目前有哪些证据/需要监控什么条件/下一次核实时间。\n\n"
        "## 本轮最容易被忽略的三个事件\n"
        "分别回答：是什么/为什么容易漏掉/接下来如何验证。"
    )


def call_gemini(prompt: str) -> str:
    if not GEMINI_KEY:
        raise RuntimeError("未配置 GEMINI_API_KEY，无法调用大模型。请在仓库 Secrets 中配置。")
    keys = GEMINI_KEYS_LIST if GEMINI_KEYS_LIST else [GEMINI_KEY]
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192, "topP": 0.95},
    }
    data = json.dumps(body).encode("utf-8")
    last_err = None
    last_quota = False
    for ki, key in enumerate(keys):
        url = f"{GEMINI_BASE_URL}/models/{MODEL}:generateContent?key={key}"
        for attempt in range(1, 3):
            try:
                req = urllib.request.Request(
                    url, data=data, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    obj = json.loads(resp.read().decode("utf-8"))
                parts = obj.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts).strip()
                if text:
                    print(f"[global_scan] 模型 {MODEL}（key#{ki + 1}）生成成功")
                    return text
                raise RuntimeError("Gemini 返回空内容：" + json.dumps(obj, ensure_ascii=False)[:500])
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:800]
                except Exception:
                    pass
                last_err = f"HTTP {e.code}: {detail}"
                print(f"[global_scan] 模型 {MODEL}（key#{ki + 1}）第 {attempt} 次失败: HTTP {e.code} {detail}", file=sys.stderr)
                if e.code == 429:
                    last_quota = True
                    if ki < len(keys) - 1:
                        break
                    time.sleep(30)
                    continue
                if 400 <= e.code < 500:
                    raise RuntimeError(
                        f"Gemini 客户端错误（请检查 GEMINI_API_KEY / GEMINI_MODEL / GEMINI_BASE_URL）: {last_err}"
                    )
                time.sleep(min(20, 5 * attempt))
                continue
            except Exception as e:  # noqa: BLE001
                last_err = e
                print(f"[global_scan] 模型 {MODEL}（key#{ki + 1}）第 {attempt} 次失败: {e}", file=sys.stderr)
                time.sleep(min(20, 5 * attempt))
                continue
    hint = "（疑似 Gemini API 配额耗尽 429，请等待配额重置或更换/升级 API Key）" if last_quota else ""
    raise RuntimeError(f"Gemini 调用失败（模型 {MODEL}，key 数 {len(keys)}）: {last_err} {hint}")


def _zhipu_request(url: str, body: dict, key: str) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_zhipu(prompt: str, search_query: str) -> str:
    """调用智谱 GLM-4-Flash（OpenAI 兼容接口），使用其内置 web_search 工具做实时联网检索。"""
    if not ZHIPU_KEY:
        raise RuntimeError("未配置 ZHIPU_API_KEY，无法调用智谱模型。请在仓库 Secrets 中配置。")
    url = f"{ZHIPU_BASE_URL}/chat/completions"
    body = {
        "model": ZHIPU_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search", "web_search": {"search_query": search_query}}],
        "tool_choice": "auto",
        "temperature": 0.3,
        "max_tokens": 8000,
    }
    last_err = None
    last_quota = False
    for attempt in range(1, 4):
        try:
            obj = _zhipu_request(url, body, ZHIPU_KEY)
            msg = (obj.get("choices") or [{}])[0].get("message", {})
            text = (msg.get("content") or "").strip()
            if not text and msg.get("tool_calls"):
                body2 = {
                    "model": ZHIPU_MODEL,
                    "messages": [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": None, "tool_calls": msg["tool_calls"]},
                        {"role": "tool", "content": "（已执行联网检索，请基于检索结果作答）", "tool_call_id": msg["tool_calls"][0].get("id", "1")},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 6000,
                }
                obj2 = _zhipu_request(url, body2, ZHIPU_KEY)
                text = (((obj2.get("choices") or [{}])[0].get("message", {}) or {}).get("content") or "").strip()
            if text:
                print(f"[global_scan] 智谱模型 {ZHIPU_MODEL} 生成成功（{len(text)} 字）")
                return text
            raise RuntimeError("智谱返回空内容：" + json.dumps(obj, ensure_ascii=False)[:500])
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:800]
            except Exception:
                pass
            last_err = f"HTTP {e.code}: {detail}"
            print(f"[global_scan] 智谱第 {attempt} 次失败: HTTP {e.code} {detail}", file=sys.stderr)
            if e.code == 429:
                last_quota = True
                time.sleep(30)
                continue
            if 400 <= e.code < 500:
                raise RuntimeError(f"智谱客户端错误（请检查 ZHIPU_API_KEY / ZHIPU_MODEL / ZHIPU_BASE_URL）: {last_err}")
            time.sleep(min(20, 5 * attempt))
            continue
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[global_scan] 智谱第 {attempt} 次失败: {e}", file=sys.stderr)
            time.sleep(min(20, 5 * attempt))
            continue
    hint = "（疑似智谱额度/限流 429，请稍后重试或检查账号额度）" if last_quota else ""
    raise RuntimeError(f"智谱调用失败（模型 {ZHIPU_MODEL}）: {last_err} {hint}")


# 行情直接走 Yahoo 免费接口（数字最可靠，不经过 LLM）
YAHOO_SYMBOLS = [
    ("道琼斯指数", "^DJI"),
    ("纳斯达克指数", "^IXIC"),
    ("标普500", "^GSPC"),
    ("10年期美债收益率", "^TNX"),
    ("美元指数", "DX-Y.NYB"),
    ("离岸人民币兑美元", "CNH=X"),
    ("布伦特原油", "BZ=F"),
    ("COMEX黄金", "GC=F"),
    ("上证指数（昨收）", "000001.SS"),
    ("恒生指数期货", "HSI=F"),
]


def fetch_overnight_table() -> str:
    """调用 Yahoo Finance 免费行情接口，构建隔夜数据表（不经 LLM）。"""
    import urllib.parse
    rows = []
    for name, sym in YAHOO_SYMBOLS:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&range=5d"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            meta = (((obj.get("chart") or {}).get("result") or [{}])[0].get("meta") or {})
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            ts = meta.get("regularMarketTime")
            if price is None:
                rows.append((name, "未检索到", "", ""))
                continue
            chg = f"{(price / prev - 1) * 100:+.2f}%" if prev else ""
            tstr = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%m-%d %H:%M UTC") if ts else ""
            if sym == "^TNX":
                price = round(price / 10, 3)  # ^TNX 是收益率×10
            rows.append((name, price, chg, tstr))
        except Exception as e:  # noqa: BLE001
            rows.append((name, "未检索到", "", type(e).__name__))
    lines = ["| 指标 | 最新值 | 涨跌幅 | 数据时间 |", "|---|---|---|---|"]
    for name, p, c, t in rows:
        lines.append(f"| {name} | {p} | {c} | {t} |")
    return "\n".join(lines)


def build_retrieve_today_prompt() -> str:
    return (
        f"现在是 {GEN_DATETIME_CN}。请用联网搜索检索「昨天 A 股收盘后到此刻」发生的、会影响今天 A 股走势的消息"
        "（政策、宏观数据、公司公告、海外市场、地缘政治、AI产业链），输出 8—15 条原始消息清单，"
        "每条格式：`- 标题（必须含具体数字） | 发布时间 | [来源标题](直达URL)`。"
        "只要事实清单，不要分析、不要建议、不要结论。检索不到几条就如实输出几条，禁止编造。"
    )


def build_retrieve_future_prompt() -> str:
    return (
        f"现在是 {GEN_DATETIME_CN}。请用联网搜索检索未来 1—14 天已排期或大概率发生的财经大事件"
        "（央行议息、经济数据发布、重磅财报、IPO、产业会议、监管节点、地缘时间点），输出 10—18 条清单，"
        "每条格式：`- 预计日期（北京时间，不确定写「日期待定」） | 事件描述（含关键数字或预期） | 状态（已确认/高可信预期/单一来源消息） | [来源](直达URL)`。"
        "只要清单，不要分析。禁止编造日期与事件。"
    )


def push_wechat(title: str, content: str) -> str:
    if not PUSHPLUS_TOKEN:
        return "跳过（未配置 PUSHPLUS_TOKEN）"
    url = "https://www.pushplus.plus/send"
    payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content}
    if PUSHPLUS_TOPIC:
        payload["topic"] = PUSHPLUS_TOPIC
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        if obj.get("code") == 200:
            return "成功"
        return f"失败(code={obj.get('code')}): {obj.get('data') or obj.get('msg')}"
    except Exception as e:  # noqa: BLE001
        return f"异常: {e}"


def _strip_code_fence(text: str) -> str:
    """去掉报告中所有 ``` 代码围栏（保留围栏内的内容），避免破坏微信 HTML 排版。"""
    t = text.strip()
    # 成对围栏：保留内部内容
    t = re.sub(r"```[a-zA-Z]*\s*\n(.*?)```", r"\1", t, flags=re.S)
    # 残留的孤立围栏行
    t = re.sub(r"^\s*```[a-zA-Z]*\s*$", "", t, flags=re.M)
    return t.strip()


def _inline(text: str) -> str:
    """将 Markdown 行内语法转换为适合微信(手机)显示的 HTML。"""
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: (
            f'<a href="{m.group(2)}" '
            f'style="color:#4dabf7;text-decoration:none;border-bottom:1px solid #4dabf7;'
            f'word-break:break-all;">{m.group(1)}</a>'
        ),
        text,
    )

    def _bare(m):
        pre, url = m.group(1), m.group(2)
        if pre in ('"', ']'):
            return m.group(0)
        a = (
            f'<a href="{url}" '
            f'style="color:#4dabf7;text-decoration:none;border-bottom:1px solid #4dabf7;'
            f'word-break:break-all;">{url}</a>'
        )
        return (pre or "") + a

    text = re.sub(r"(.)?(https?://[^\s<)]+)", _bare, text)
    text = re.sub(r"\*\*(.+?)\*\*", r'<strong style="font-weight:700;color:#ffffff;">\1</strong>', text)
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#1e2128;padding:1px 4px;border-radius:3px;'
        r'font-size:13px;color:#ff7b72;">\1</code>',
        text,
    )
    # 状态标注着色：【已确认】绿 / 【高可信预期】橙 / 【单一来源消息】【市场传闻】灰红
    text = text.replace("【已确认】", '<strong style="color:#3fb950;font-weight:700;">【已确认】</strong>')
    text = text.replace("【高可信预期】", '<strong style="color:#ffa940;font-weight:700;">【高可信预期】</strong>')
    text = text.replace("【单一来源消息】", '<strong style="color:#c9d1d9;font-weight:700;">【单一来源消息】</strong>')
    text = text.replace("【市场传闻】", '<strong style="color:#ff7b72;font-weight:700;">【市场传闻】</strong>')
    return text


def markdown_to_html(md: str) -> str:
    """将 Markdown 报告渲染为 iPhone 15 Pro 友好的 HTML（PushPlus 用 HTML 渲染）。"""
    md = _strip_code_fence(md)
    lines = md.splitlines()
    out = []
    list_type = None
    list_items = []

    def flush_list():
        nonlocal list_type, list_items
        if list_type and list_items:
            tag = "ul" if list_type == "ul" else "ol"
            lis = "".join(f'<li style="margin:4px 0;">{it}</li>' for it in list_items)
            out.append(f'<{tag} style="margin:6px 0;padding-left:20px;">{lis}</{tag}>')
        list_type, list_items = None, []

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_list()
            continue
        if re.match(r"^\s*([-*_])\1{2,}\s*$", line):
            flush_list()
            out.append('<hr style="border:none;border-top:1px solid #2a2f37;margin:12px 0;">')
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush_list()
            level = len(m.group(1))
            txt = _inline(m.group(2))
            if level == 1:
                out.append(f'<h1 style="font-size:20px;color:#ffa940;font-weight:700;border-bottom:2px solid #ffa940;padding-bottom:6px;margin:18px 0 10px;">{txt}</h1>')
            elif level == 2:
                out.append(f'<h2 style="font-size:17px;color:#5cc8ff;font-weight:700;border-left:4px solid #ffa940;padding-left:8px;margin:16px 0 8px;">{txt}</h2>')
            elif level == 3:
                out.append(f'<h3 style="font-size:15.5px;color:#ffa940;font-weight:700;margin:12px 0 6px;">{txt}</h3>')
            else:
                out.append(f'<h4 style="font-size:14.5px;color:#c9d1d9;font-weight:700;margin:10px 0 4px;">{txt}</h4>')
            continue
        if line.lstrip().startswith(">"):
            flush_list()
            out.append(f'<div style="border-left:3px solid #3a4150;padding:4px 10px;color:#9aa3ad;background:rgba(255,255,255,0.04);margin:6px 0;">{_inline(line.lstrip()[1:].strip())}</div>')
            continue
        lm = re.match(r"^\s*[-*]\s+(.*)$", line)
        olm = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if lm:
            if list_type != "ul":
                flush_list()
                list_type = "ul"
            list_items.append(_inline(lm.group(1)))
            continue
        if olm:
            if list_type != "ol":
                flush_list()
                list_type = "ol"
            list_items.append(_inline(olm.group(1)))
            continue
        flush_list()
        out.append(f'<p style="margin:6px 0;">{_inline(line)}</p>')

    flush_list()
    body = "".join(out)
    wrapper = (
        '<div style="max-width:100%;background:#111418;color:#e6e8eb;'
        'font-family:-apple-system,BlinkMacSystemFont,'
        '&quot;PingFang SC&quot;,&quot;Helvetica Neue&quot;,Arial,sans-serif;'
        'font-size:15px;line-height:1.75;word-break:break-word;'
        'padding:14px 14px 18px;border-radius:14px;">'
        f"{body}"
        "</div>"
    )
    return wrapper


def make_summary(report: str) -> str:
    """返回整篇报告的手机 HTML（含全部章节），超长则截断保护。"""
    html = markdown_to_html(report)
    if len(html) > 40000:
        html = html[:39000] + '<p style="color:#9aa3ad;margin:6px 0;">（内容较长，已截断，完整版见仓库 global_scan 目录）</p></div>'
    return html


def main() -> int:
    if not (ZHIPU_KEY or GEMINI_KEY):
        print("[global_scan] 未配置 ZHIPU_API_KEY 或 GEMINI_API_KEY，无法检索新闻。", file=sys.stderr)
        return 1
    analyzer = f"Gemini {MODEL}（联网搜索）" if GEMINI_KEY else "智谱 GLM-4-Flash"
    print(f"[global_scan] 开始生成 {GEN_DATE} 报告：深度分析={analyzer}")

    def _gen(prompt: str, search_query: str) -> str:
        """检索/生成：优先智谱（web_search），失败且有 Gemini key 时本节回退 Gemini。"""
        if ZHIPU_KEY:
            try:
                return call_zhipu(prompt, search_query)
            except Exception as e:  # noqa: BLE001
                if GEMINI_KEY:
                    print(f"[global_scan] 智谱失败，本节回退 Gemini: {e}", file=sys.stderr)
                    return call_gemini(prompt)
                raise
        return call_gemini(prompt)

    # Step 0：隔夜行情（Yahoo 免费接口直取，数字不经 LLM，最可靠）
    try:
        quotes_md = fetch_overnight_table()
        print("[global_scan] 隔夜行情获取成功")
    except Exception as e:  # noqa: BLE001
        print(f"[global_scan] 隔夜行情获取失败: {e}", file=sys.stderr)
        quotes_md = "（行情接口失败，请基于检索材料中的数字）"

    # Step 1：今日因子 —— Gemini 原生联网搜索一次出深度卡片；仅智谱时两步走（先检索清单再写作）
    try:
        if GEMINI_KEY:
            today_md = call_gemini(build_today_prompt(quotes_md)).strip()
        else:
            news_md = _gen(
                build_retrieve_today_prompt(),
                f"{GEN_DATE} A股 盘前 要闻 政策 公告 隔夜美股 最新",
            ).strip()
            today_md = _gen(
                build_today_prompt(quotes_md + "\n\n【已检索到的新闻清单】\n" + news_md),
                f"{GEN_DATE} 今日A股 盘前 政策 北向资金",
            ).strip()
        print(f"[global_scan] 今日因子生成成功（{len(today_md)} 字）")
    except Exception as e:  # noqa: BLE001
        print(f"[global_scan] 今日因子生成失败（继续）: {e}", file=sys.stderr)
        today_md = "（本节生成失败）"

    # Step 2：明日因子 + 日历，同样策略
    try:
        if GEMINI_KEY:
            nextday_md = call_gemini(build_nextday_prompt(quotes_md)).strip()
        else:
            events_md = _gen(
                build_retrieve_future_prompt(),
                "未来一周 央行议息 经济数据发布 财报 IPO 产业会议 时间表",
            ).strip()
            nextday_md = _gen(
                build_nextday_prompt(quotes_md + "\n\n【已检索到的未来事件清单】\n" + events_md),
                f"{NEXT_DATE} 未来一周 央行议息 经济数据 财报 IPO",
            ).strip()
        print(f"[global_scan] 明日因子与日历生成成功（{len(nextday_md)} 字）")
    except Exception as e:  # noqa: BLE001
        print(f"[global_scan] 明日因子与日历生成失败（继续）: {e}", file=sys.stderr)
        nextday_md = "（本节生成失败）"

    report = (
        f"# 全球事件与资金流向扫描 · {GEN_DATE}\n\n"
        "## 一、隔夜与盘前关键数据\n\n"
        f"{quotes_md}\n\n"
        f"## 二、影响【今日 {GEN_DATE}】走势的因子\n\n"
        f"{today_md}\n\n"
        f"## 三、影响【明日 {NEXT_DATE}】走势的因子与未来两周日历\n\n"
        f"{nextday_md}\n"
    )

    out_dir = "global_scan"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{GEN_DATE}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"[global_scan] 报告已写入 {out_path}（{len(report)} 字）")

    status = push_wechat(f"全球事件与资金扫描·今日明日因子 {GEN_DATE}", make_summary(report))
    print(f"[global_scan] 微信推送：{status}")

    # 尽量把报告提交回仓库（best-effort，失败不影响主流程）
    try:
        import subprocess
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=False)
        subprocess.run(["git", "config", "user.name", "github-actions"], check=False)
        subprocess.run(["git", "add", out_path], check=False)
        res = subprocess.run(
            ["git", "commit", "-m", f"docs(global-scan): 添加 {GEN_DATE} 全球事件扫描报告"],
            capture_output=True, text=True, check=False,
        )
        if res.returncode == 0:
            subprocess.run(["git", "push"], capture_output=True, text=True, check=False)
            print("[global_scan] 报告已提交并推送至仓库")
        else:
            print("[global_scan] 无需提交或提交跳过（可能无变更/无推送权限）")
    except Exception as e:  # noqa: BLE001
        print(f"[global_scan] 报告提交仓库失败（已忽略）: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
