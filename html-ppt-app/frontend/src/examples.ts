export interface ExampleCard {
  id: string;
  title: string;
  description: string;
  badge: string;
  prompt: {
    topic: string;
    language: string;
    style: string;
    slide_count: number;
    audience: string;
    content: string;
    extra_requirements: string;
  };
  standaloneUrl: string;
}

export const EXAMPLE_CARDS: ExampleCard[] = [
  {
    id: "japan-tour",
    title: "日本旅游计划",
    description: "三个方案的详细对比：秋天红叶、Deepavali 高效出行、冬天北海道雪景。展示轻量搜索模式生成效果。",
    badge: "8 pages / 中文 / 明亮风格",
    prompt: {
      topic: "日本旅游计划",
      language: "中文",
      style: "明亮",
      slide_count: 8,
      audience: "朋友",
      content:
        "方案 A：秋天红叶，最推荐\n" +
        "时间：11月21日–11月29日，或 11月28日–12月6日\n" +
        " 请假：5天\n 天数：9天\n" +
        "路线建议：大阪进，东京出 / 或大阪往返\n" +
        " Day 1：新加坡 → 大阪\n" +
        " Day 2–4：京都：岚山、东福寺、清水寺、南禅寺、永观堂\n" +
        " Day 5：奈良 / 宇治\n Day 6：大阪\n" +
        " Day 7–8：东京 / 箱根 / 河口湖\n Day 9：回新加坡\n" +
        "这个窗口最适合第一次认真看日本秋色。日本官方旅游资料说，11月日本大部分地区天气清爽、红叶明显；东京和京都的红叶通常在 11月下旬到12月初更稳。\n\n" +
        "方案 B：利用 Deepavali，年假效率最高\n" +
        "时间：11月7日–11月15日\n 请假：4天\n 天数：9天\n" +
        "路线建议：东京 + 日光 + 箱根 / 河口湖\n" +
        " Day 1：新加坡 → 东京\n Day 2–3：东京\n" +
        " Day 4–5：日光，看湖区、神社、早秋色\n" +
        " Day 6：箱根 / 河口湖\n Day 7–8：东京自由安排\n Day 9：回新加坡\n" +
        "这个时间京都可能还没到最好状态，但日本红叶是从北向南、高海拔向低海拔推进，11月上旬更适合日光、长野、富士五湖这类稍冷区域。\n\n" +
        "方案 C：冬天雪景，北海道\n" +
        "时间：12月19日–12月27日\n 请假：4天\n 天数：9天\n" +
        "路线建议：札幌 + 小樽 + 登别 + 旭川/美瑛\n" +
        " Day 1：新加坡 → 札幌\n Day 2：札幌\n Day 3：小樽\n Day 4：登别温泉\n" +
        " Day 5–6：旭川 / 美瑛 / 富良野\n Day 7：札幌购物、夜景、灯饰\n Day 8：机动日\n Day 9：回新加坡\n" +
        "优点是雪景、温泉、城市节奏比较舒服。缺点是交通受天气影响更大，且圣诞周价格偏高。",
      extra_requirements: "调研一下各个方案的成本",
    },
    standaloneUrl: "/Examples/Example_Japan Tour/standalone.html",
  },
  {
    id: "semiconductor",
    title: "亚太半导体产业报告",
    description: "2025-2026 全景分析：市场份额、供应链竞争格局、技术演进与投资机会。展示深度研究模式效果。",
    badge: "12 pages / 中文 / 市场研究",
    prompt: {
      topic: "亚太半导体产业报告",
      language: "Chinese",
      style: "市场研究",
      slide_count: 12,
      audience: "general audience",
      content:
        "# 亚太半导体产业洞察：2025—2026全景分析\n\n" +
        "## 一、市场份额与产业总览\n\n" +
        "全球半导体产业正处于新一轮增长周期。根据WSTS预测，2025年全球半导体市场增速将达11.2%，市场规模增至约7,009亿美元；2026年市场再增8.5%，达到7,607亿美元。\n\n" +
        "在全球竞争格局中，美国以44%的综合收入份额占据绝对主导地位。东亚作为全球半导体产业的关键一极，韩国占16%、中国台湾占15%、日本占10%，合计贡献全球41%的份额。\n\n" +
        "从企业维度看，行业高度集中，前35大企业占据总收入的80%，其中前四名（NVIDIA、台积电、三星、英特尔）合计占比高达31%。\n\n" +
        "## 二、上中下游供应链分析\n\n" +
        "半导体上游主要包括芯片设计（EDA/IP）、半导体设备制造和半导体材料供应。半导体设备领域呈现美日荷三足鼎立格局。光刻机由荷兰ASML、日本佳能和尼康主导，最先进的EUV光刻机100%来自ASML。\n\n" +
        "半导体材料领域，日本具有绝对垄断地位——19种核心半导体材料中，日本有14种占据全球第一的市场份额。\n\n" +
        "晶圆代工（Foundry）是亚太最具优势的领域。台积电以69.9%的营收市占率稳居第一，三星以7.2%位列第二，中芯国际以5.32%排第三。\n\n" +
        "## 三、主要技术演进\n\n" +
        "2nm制程是摩尔定律延续的关键节点。台积电已于2025年Q4启动2nm量产，三星完成Exynos 2600开发，日本Rapidus完成首块2nm GAA晶圆试制。\n\n" +
        "先进封装与Chiplet正在从\"配角\"走向中心。AI算力需求是亚太半导体最核心的增长引擎。\n\n" +
        "## 四、风险\n\n" +
        "地缘政治风险是主要风险源。美国出口管制从\"单边卡脖子\"升级为\"全球合围\"。日本在光刻胶等核心材料领域接近垄断，存在供应链集中风险。\n\n" +
        "（完整报告约 8,000 字，含详细数据表格、公司对比和投资分析）",
      extra_requirements: "",
    },
    standaloneUrl: "/Examples/Example_Semiconductor/standalone.html",
  },
  {
    id: "smartphone",
    title: "2026 旗舰手机对比",
    description: "iPhone 17 Pro Max vs S26 Ultra vs Mate 80 Pro 全方位横评：性能、影像、续航、价格、购买建议。展示 Pipeline 无搜索模式。",
    badge: "10 pages / English / 暗色 / 对比评测",
    prompt: {
      topic: "2026 Flagship Smartphone Comparison",
      language: "English",
      style: "暗色",
      slide_count: 10,
      audience: "Consumer",
      content:
        "2026 Flagship Smartphone Comparison: iPhone 17 Pro Max vs Samsung S26 Ultra vs Huawei Mate 80 Pro\n\n" +
        "I. Core Performance Comparison\n" +
        "iPhone 17 Pro Max: Apple A19 Pro (3nm), Hexa-core (2x 4.26GHz), 12GB LPDDR5X, AnTuTu ~2,319,000\n" +
        "Samsung S26 Ultra: Snapdragon 8 Gen 5 (2nm), Octa-core (2x 4.74GHz), 12/16GB RAM, AnTuTu >3,720,000\n" +
        "Huawei Mate 80 Pro: Kirin 9030/9030 Pro, Octa-core, 12/16GB RAM, AnTuTu ~940,000\n\n" +
        "II. Hardware Configuration\n" +
        "All three: 6.9\" 120Hz LTPO OLED, IP68. iPhone: Triple 48MP, ~4832mAh, 40W. Samsung: 200MP+50MP+50MP+10MP, 5000mAh, 45W, S Pen. Huawei: 50MP RYYB variable aperture, 5750-6000mAh, 100W wired + 80W wireless.\n\n" +
        "III. User Experience\n" +
        "Gaming: iPhone ≥59fps @41°C (most stable), Huawei active cooling (best sustained), Samsung highest burst but throttles after ~4min.\n" +
        "Signal: Huawei Lingxi antenna leads, iPhone middling.\n" +
        "OS: iOS 26 vs One UI 8.5 (7yr updates) vs HarmonyOS 6.0 Pure.\n\n" +
        "IV. Special Features\n" +
        "Satellite: Huawei dual-mode (BeiDou+Tiantong), Samsung Tiantong, iPhone none. AI: Apple on-device privacy, Samsung Galaxy AI triple-engine, Huawei Pangu AI hybrid.\n\n" +
        "V. Price (May 2026, 256GB)\n" +
        "iPhone 17 Pro Max: ¥9999 → ~¥8999 (618 promo)\n" +
        "Samsung S26 Ultra: ¥9999 → ~¥9999 (limited discounts)\n" +
        "Huawei Mate 80 Pro: ¥6999 → ~¥4699-5800 (subsidies)\n\n" +
        "VI. Buying Guide\n" +
        "Apple ecosystem + video → iPhone. Extreme specs + S Pen → Samsung. Signal + battery + value → Huawei (under ¥5000).",
      extra_requirements: "Do a buying recommendation",
    },
    standaloneUrl: "/Examples/Example_Smartphone/standalone.html",
  },
  {
    id: "quantum-computing",
    title: "全球量子计算产业洞察",
    description: "市场规模、技术路线竞争、20亿美元 CHIPS 法案投资解读、AI 与量子融合趋势。展示长文本 Pipeline 效果。",
    badge: "17 pages / 中文 / 科技 / 阅读型",
    prompt: {
      topic: "全球量子计算产业洞察",
      language: "中文",
      style: "粉蓝明亮、专业、科技、市场研究风、适合战略分析阅读型 deck",
      slide_count: 17,
      audience: "战略投资部",
      content:
        "# 全球量子计算产业洞察：市场规模、供应链竞争格局与技术演进（2026）\n\n" +
        "> 本报告涵盖截至2026年5月的最新信息，特别聚焦美国政府以20亿美元重注量子计算的最新政策动向。\n\n" +
        "## 一、市场份额与产业总览\n\n" +
        "全球量子计算产业正从实验室走向商业化前夕。根据QY Research数据，2025年全球量子计算市场规模约为16.09亿美元，预计到2032年达到126亿美元，CAGR高达34.7%。\n\n" +
        "北美以约54%的全球市场份额占据绝对主导地位，亚太地区（约30%）和欧洲紧随其后。\n\n" +
        "2025年量子计算行业投融资创历史新高，全年融资总额接近100亿美元。PsiQuantum完成10亿美元E轮融资（量子计算史上最大单轮），Quantinuum投前估值达100亿美元。\n\n" +
        "## 二、供应链分析与竞争格局\n\n" +
        "量子计算已形成覆盖上游硬件、中游系统平台、下游场景应用的完整产业链。超导、离子阱、光量子和中性原子四大技术路线齐头并进，主流路线尚未收敛。\n\n" +
        "IBM（超导，获美国政府10亿美元建量子晶圆厂）、谷歌（Willow芯片，AI驱动纠错）、IonQ（离子阱，Q1营收6470万美元，同比+755%）、PsiQuantum（光量子，百万量子比特设施在建）等企业领跑。\n\n" +
        "## 三、美国20亿美元CHIPS法案投资（2026年5月）\n\n" +
        "美国商务部向9家量子计算企业提供总额20.13亿美元联邦专项激励资金，覆盖5大物理模态，是迄今全球最大规模政府量子计算专项投资。\n\n" +
        "## 四、主要技术演进\n\n" +
        "AI赋能量子计算：AI辅助纠错编码将通用量子计算机门槛从百万物理比特降至约两万。中性原子路线异军突起——中科酷原\"汉原2号\"功耗低于7千瓦，可在普通环境部署。\n\n" +
        "（完整报告约 15,000 字，含 17 张详细 slides、公司对比表、投资分析）",
      extra_requirements:
        "请生成专业阅读型 HTML PPT，强调产业链、市场格局、技术趋势、公司对比、投资机会与风险。请保留报告中的公司名、数据、年份、技术节点，不要过度总结。",
    },
    standaloneUrl: "/Examples/Example_Quantum Computing Industry Insight/standalone.html",
  },
];
