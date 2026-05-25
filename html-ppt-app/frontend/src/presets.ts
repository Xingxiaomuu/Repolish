export interface PresetCard {
  id: string;
  title: string;
  description: string;
  badge: string;
  fill: {
    topic: string;
    language: string;
    style: string;
    slide_count: number;
    audience: string;
    extra_requirements: string;
  };
}

export const PRESET_CARDS: PresetCard[] = [
  {
    id: "semiconductor",
    title: "半导体产业报告",
    description:
      "适合产业链分析、公司比较、投资机会判断和战略研究汇报。",
    badge: "12 pages / Market Research / Reading Deck",
    fill: {
      topic: "半导体产业报告",
      language: "中文",
      style: "粉蓝明亮、专业、科技、市场研究风、适合战略分析阅读型 deck",
      slide_count: 12,
      audience: "战略投资部",
      extra_requirements:
        "请生成专业阅读型 HTML PPT，强调产业链、市场格局、技术趋势、公司对比、投资机会与风险。请保留报告中的公司名、数据、年份、技术节点，不要过度总结。",
    },
  },
  {
    id: "audio-market",
    title: "亚太音频市场调研报告",
    description:
      "适合 TWS、OWS、空间音频、端侧 AI 与消费电子供应链研究。",
    badge: "12 pages / Market Research / Reading Deck",
    fill: {
      topic: "亚太音频市场调研报告",
      language: "中文",
      style: "明亮、清爽、专业、消费电子科技感、市场洞察报告风格",
      slide_count: 12,
      audience: "公司内部战略 / 技术规划团队",
      extra_requirements:
        "请生成专业阅读型 HTML PPT，重点覆盖市场趋势、区域格局、供应链结构、玩家分类、技术机会窗口和战略建议。请保留原文中的数据、公司名、产品形态和技术关键词。",
    },
  },
];
