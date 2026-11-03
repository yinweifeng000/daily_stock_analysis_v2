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

## 十一、最终报告格式

### 0. 今日/明日走势因子清单（最高优先级，必须最先输出）
分别列出「影响今日走势的因子」与「影响明日走势的因子」，每条一行，格式：
`因子描述 —— 状态：【已确认/高可信预期/单一来源消息/市场传闻】—— 方向：利多/利空/中性 —— 评分：0-100 —— 关键验证信号`
今天和明天各 5—12 条，按评分从高到低排序，已确认因子排前、未确认因子排后。

### 1. 执行摘要
列出未来14天最重要的10—20个事件，按潜在资金影响和紧迫程度排序。

### 2. 未来14天逐日事件日历
以北京时间列出每天的宏观数据、央行会议、财报、IPO申报预期、产业会议、监管截止日期和地缘政治风险节点。

### 3. 全球重大事件排行榜
每条事件包括：名称、发生时间、事实与预期的区分、可信度、影响评分、潜在受益和受损资产、A股映射、市场是否已提前交易。

### 4. AI与科技资本开支专项
单独列出全球AI公司、云厂商、芯片公司和数据中心企业的IPO、融资、财报、订单、资本开支、产品发布和监管事件。

### 5. IPO及重大融资专项
列出所有可能在未来14天提交申请、更新招股书、开始路演、定价或挂牌的重大公司，包括尚未正式确认但已有可信媒体报道的事件。

### 6. 地缘政治与能源风险专项
重点分析战争、制裁、停火谈判、航运、能源供应及油价的不同情景。

### 7. 全球资金流向推演
说明不同事件可能使资金流向哪些资产和行业，以及是否可能发生跨市场、跨资产的资金再配置。

### 8. A股未来1—2周行业轮动清单
区分：已经充分交易的方向、正在开始交易的方向、尚未充分交易但催化临近的方向、逻辑存在但缺乏资金或业绩验证的方向。

### 9. 高影响但低确定性事件
专门列出可能改变市场格局、但消息尚未正式确认的事件，标注监控条件和下一次核实时间。

### 10. 反向查漏审计
明确列出完成了哪些类别的搜索、哪些来源不可访问、哪些事件尚未核实，以及仍可能存在的盲区。

### 11. 未来24—72小时监控清单
列出最值得反复核实的事件及具体观察信号。

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


def build_prompt() -> str:
    header = (
        f"今天是 {GEN_DATETIME_CN}，明天是 {NEXT_DATE}。请以当前实际时间为扫描基准时间，立即开始联网检索。\n"
        "输出要求：用中文 Markdown 输出报告正文（不要用代码块包裹），**每条事件/数据务必附真实可点击的来源链接，"
        "使用 [标题](URL) 格式，禁止虚构或占位链接**。若输出篇幅受限，优先保证「### 0. 今日/明日走势因子清单」和"
        "「### 1. 执行摘要」完整，其后章节允许适度精简。\n"
        "以下是完整的扫描任务说明：\n\n"
        "# 全球重大事件与资金流向深度扫描提示词（防遗漏增强版）\n"
    )
    return header + PROMPT_CORE


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


def call_zhipu(prompt: str) -> str:
    """调用智谱 GLM-4-Flash（OpenAI 兼容接口），使用其内置 web_search 工具做实时联网检索。"""
    if not ZHIPU_KEY:
        raise RuntimeError("未配置 ZHIPU_API_KEY，无法调用智谱模型。请在仓库 Secrets 中配置。")
    url = f"{ZHIPU_BASE_URL}/chat/completions"
    search_query = f"{GEN_DATE} 全球宏观 央行政策 AI IPO 地缘政治 资金流向 大宗商品 A股"
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
    """去掉模型偶尔包裹的 ```markdown ... ``` 代码围栏。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
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
    if ZHIPU_KEY:
        provider, model_name = "智谱 GLM-4-Flash", ZHIPU_MODEL
    elif GEMINI_KEY:
        provider, model_name = "Gemini", MODEL
    else:
        print("[global_scan] 未配置 ZHIPU_API_KEY 或 GEMINI_API_KEY，无法生成报告。", file=sys.stderr)
        return 1
    print(f"[global_scan] 开始生成 {GEN_DATE} 全球事件扫描报告，提供方={provider}，模型={model_name}")
    try:
        if ZHIPU_KEY:
            try:
                report = call_zhipu(build_prompt())
            except Exception as e:  # noqa: BLE001
                if GEMINI_KEY:
                    print(f"[global_scan] 智谱调用失败，回退 Gemini: {e}", file=sys.stderr)
                    report = call_gemini(build_prompt())
                else:
                    raise
        else:
            report = call_gemini(build_prompt())
    except Exception as e:  # noqa: BLE001
        print(f"[global_scan] 生成失败: {e}", file=sys.stderr)
        return 1

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
