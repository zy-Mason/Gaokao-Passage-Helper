# Gaokao-Passage-Helper

一个面向高考作文的**素材生产工具**。输入一个主题词（如「苏轼」「陶渊明」「AI」），自动检索资料并产出一份结构化、可直接用于议论文的素材卡。

---

## 一、它做什么

给一个主题词，输出一份包含以下字段的素材卡：

| 字段 | 含义 |
|---|---|
| `name` | 素材名称（人物名 / 事件名） |
| `tag` | 该素材可对应的作文主题标签 |
| `summary` | 精炼总结，用于考前速览快速唤醒记忆 |
| `detail` | 展开的细节、名言、小众但有力的视角；**每条自带 tag 标注** |
| `transcend` | 思辨点 / 深刻点，按深度排序，用于把议论写深 |
| `note` | 使用建议：适合放在议论文的什么位置、有哪些坑要避 |
| `cache` | 使用示例，覆盖多个角度，凝练深刻 |

设计目标不是「堆生平」，而是产出**有论证价值、有辨识度**的素材，并明确告诉你**该怎么用**。

---

## 二、工作原理

流程分两阶段，分别走 DeepSeek 的两个不同接口：

```
主题词
  │
  ├─ 阶段 1：get_anthropic()
  │    Anthropic 兼容接口 https://api.deepseek.com/anthropic
  │    模型 deepseek-flash，开启 web_search 工具（max_uses=90）、effort=high
  │    作用：真的去检索资料，产出一份「分析态」的素材文本
  │    记录：思考内容 + 输出内容 → log/{主题词}.md
  │
  ├─ 阶段 2：get_openai()
  │    OpenAI 兼容接口 https://api.deepseek.com
  │    模型 deepseek-flash，JSON 模式，开启思考
  │    作用：把上一步的文本整理成 JSON
  │    记录：思考内容 + 原始 JSON → log/{主题词}.md（续写）
  │
  └─ parse_sucai()
       把 JSON 渲染成人类易读的纯文本 → 素材/{主题词}.txt
```

**关于阶段 2 的 `fake_mat_finder`**：整理 JSON 时，系统提示词故意换成一个**不含检索能力**的版本（措辞是「思考要求」而非「搜索要求」）。目的是让模型认为"资料已经拿到了，现在只做格式化"，从而**不再尝试检索、也不再质疑资料来源**，专心完成结构化输出。

---

## 三、目录结构

```
Gaokao-Passage/
├── src/
│   ├── tool.py            # 核心：API 调用、日志、JSON→文本渲染
│   ├── prompt.py          # 提示词：mat_finder / fake_mat_finder / resformat
│   ├── main_single.py    # 入口：单个素材
│   ├── main_batch.py     # 入口：批量素材
│   ├── log/               # 运行日志（自动生成，Markdown）
│   │   └── {主题词}.md
│   └── 素材/              # 成品素材卡（自动生成）
│       └── {主题词}.txt
├── requirements.txt
├── THIRD-PARTY-NOTICES.md
├── LICENSE                # AGPL-3.0
└── README.md
```

---

## 四、环境准备

- Python 3.10+
- 可访问 `api.deepseek.com` 的网络环境
- 一个 DeepSeek API Key

### 安装依赖

```bash
pip install -r requirements.txt
```

`requirements.txt` 只有两项：`openai`、`anthropic`，并带最低版本约束。

> 注意：`tool.py` 用到了 `output_config={"effort": "high"}` 等较新的参数，**anthropic 包版本过低会直接报 `TypeError: unexpected keyword argument`**。若遇到此错误，请升级：`pip install -U anthropic`

### 配置 API Key

代码通过环境变量 `DEEPSEEK_API_KEY` 读取密钥：

```python
# tool.py
api_key=os.getenv('DEEPSEEK_API_KEY')
```

**Windows（Git Bash）**

```bash
export DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxx"
```

**Windows（PowerShell）**

```powershell
$env:DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxx"
```

**临时单次运行**

```bash
DEEPSEEK_API_KEY="sk-xxxx" python main_single.py
```



## 五、使用方法

> **重要：必须在 `src/` 目录下运行。**
> 脚本内部使用的是 `log/`、`素材/` 这类相对路径，且 `import prompt` 依赖 `src/` 在模块搜索路径中。在项目根目录或其它目录运行，会导致导入失败，或把输出写到错误的位置。

```bash
cd src
```

### 5.1 单个素材

```bash
python main_single.py
```

交互过程：

```
输入素材名：苏轼
```

回车即开始；若成品已存在，会先询问是否覆盖。完成后生成 `素材/苏轼.txt`。

### 5.2 批量素材

```bash
python main_batch.py
```

交互过程：

```
输入一组素材名，用空格分割：苏轼 陶渊明 杜甫
即将整理这些素材，确认请输入 y 回车
['苏轼', '陶渊明', '杜甫']
y
```

必须输入 `y`（不区分大小写）才会执行，其它任何输入都会直接退出。素材名之间用空白字符分隔，连续空格或 Tab 都可以。

逐个素材串行处理，每个素材都会完整走一遍两阶段流程。素材越多、耗时越长。已存在的成品会跳过或按你的选择覆盖；单个素材失败不会中断整批，最后会汇总失败列表。

---

## 六、输出说明

每个素材产生两个文件：

### `素材/{主题词}.txt` — 成品素材卡

由 `parse_sucai()` 渲染，纯文本、无 Markdown 语法，形如：

```
苏轼

tags:
  旷达·逆境, 家国担当·实干, 民本·为民

summary:
 苏轼（1037—1101），字子瞻，号东坡居士……

detail:
1.乌台诗案的九死一生：……
tag: 旷达·逆境 生死观 亲情·手足

2.王安石一句话救他：……
tag: 人格·交友

transcend:
  - "残疾"的普遍化……

note:
  - 别把他当"身残志坚"的符号使用……

cache:
  - （逆境）苏轼的豁达不是天赐……
```

### `log/{主题词}.md` — 运行日志

追加写入，用 Markdown 章节组织，按「阶段」记录每次请求：

```
# 苏轼

> 运行日志 · 创建于 2026-10-31 10:00:00

## 阶段 1 · 检索与素材整理

> 记录时间：2026-10-31 10:00:00

### 思考内容
……

### 输出内容
……

## 阶段 2 · JSON 整理（第 1 次请求）

### 思考内容
……

### 输出内容

````json
{ …原始 JSON… }
````
```

用于排查「素材为什么是这样」。想核对某条信息是否真的来自检索、或想手动修正 JSON，看这个文件。阶段 2 的 JSON 解析失败等警告会以引用块（`> **[WARN]** …`）追加在同一个文件里；阶段 2 的 JSON 修正重试也会作为新的章节追加。单个模式还会额外生成 `log/{主题词}json.md`，单独留档原始 JSON。

---

## 七、提示词说明（`prompt.py`）

| 变量 | 用途 |
|---|---|
| `mat_finder` | 阶段 1 的系统提示词，**带检索**。规定角色、搜索方向、输出字段与质量底线 |
| `fake_mat_finder` | 阶段 2 的系统提示词，**不带检索**，结构与 `mat_finder` 基本一致，仅把「搜索要求」改为「思考要求」 |
| `resformat` | 阶段 2 的用户提示词，给出 JSON 格式示例 |

想调整素材风格（比如更侧重名言、或更强调思辨），改这几个提示词即可，无需动代码。

---

## 八、常见问题

**Q：报 `ModuleNotFoundError: No module named 'prompt'`**
没有在 `src/` 目录下运行。先 `cd src`。

**Q：`log/` 里只有一个空文件，没有素材产出**
说明阶段 1 抛出了异常导致流程中断。查看终端报错信息，常见原因是 API Key 未设置或额度不足。

**Q：素材内容看起来像模型编的，不像真检索过**
本工具的检索依赖上游对 `web_search` 工具的**服务端代执行**能力，请确认所用接口确实支持该工具。核对方法是查看 `log/{主题词}.md` 中的思考内容是否出现真实检索痕迹。

**Q：重复运行同一主题词，会不会把内容越写越长？**
不会。写入前会检查 `素材/{主题词}.txt` 是否存在：单个模式会询问是否覆盖，批量模式会统一询问是否覆盖已存在的素材；确认覆盖后以覆盖模式（`mode="w"`）写入。选择不覆盖则跳过。

**Q：报 400 错误，提示 `max_tokens` 超限**
`tool.py` 中写死了 `max_tokens=100000`，若模型上限更低会报错。可在 `get_anthropic()` 与 `get_openai()` 两处调小。

**Q：想换模型**
模型名 `deepseek-flash` 在 `tool.py` 中出现两次（`get_anthropic()` 与 `get_openai()`），两处都要改。

---

## 九、已知限制

- **必须在 `src/` 下运行**，路径与模块导入均为相对形式，未做绝对路径处理。
- **API 调用本身没有重试**。网络错误、限流等仍会让当前素材失败。批量模式下单个素材失败会记录到失败列表并继续处理后续素材，最后统一汇总；单个模式失败则直接抛出异常。
- **阶段 2 的 JSON 解析失败会自动修正**：把报错信息追加到对话中，要求模型重新输出，最多重试 2 次；仍失败则按解析失败文本写入成品。
- **阶段 2 直接取 `reasoning_content` 属性**，若接口未返回该字段会抛 `AttributeError`。
- **串行处理，无并发**。批量素材耗时较长。

---

## 十、许可

本项目采用 **AGPL-3.0**，详见 [LICENSE](LICENSE)。
第三方依赖的许可信息见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

素材内容由大模型生成，**请在使用前自行核实事实与人名、引文的准确性**，尤其是需要标注为"原话"的引语。
