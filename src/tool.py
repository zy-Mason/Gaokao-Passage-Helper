from anthropic import Anthropic
from openai import OpenAI
from datetime import datetime
import os
import re
import sys
import prompt
import json

MAX_JSON_RETRIES = 2
LOG_DIR = "log"
KNOWN_FIELDS = ("name", "tag", "detail", "transcend", "note", "cache")# 已知字段

def get_file_object(file_path: str,mode :str="a",encoding="utf-8"):
    """
    传入一个文件路径字符串。
    如果路径不存在，则创建对应的目录和空文件。
    最后返回一个打开的文件对象（读写模式，指针在开头）。
    """
    # 获取文件所在目录
    directory = os.path.dirname(file_path)
    # 如果目录非空且不存在，则递归创建目录
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    # 如果文件不存在，则创建一个空文件
    if not os.path.exists(file_path):
        # 使用 'w' 模式创建空文件后立即关闭
        with open(file_path, 'w', encoding=encoding):
            pass

    # 以读写模式打开文件（文件已存在，不会清空内容，指针在开头）
    return open(file_path, mode, encoding=encoding)


def _now() -> str:
    """当前时间，用于在日志里标注记录时刻。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _demote_headings(text: str, levels: int = 3) -> str:
    """整体下调 Markdown 标题级别，避免 AI 输出自带的标题打乱日志层级。"""
    return re.sub(
        r"(?m)^(#{1,6})(?=\s)",
        lambda match: "#" * min(len(match.group(1)) + levels, 6),
        text,
    )


def _append_log(topic: str, markdown: str) -> None:
    """把一段 Markdown 追加到 log/{topic}.md，新建文件时补上标题与创建时间。"""
    path = f"{LOG_DIR}/{topic}.md"
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    with get_file_object(path, "a", encoding="utf-8") as log_file:
        if is_new:
            log_file.write(f"# {topic}\n\n> 运行日志 · 创建于 {_now()}\n\n")
        log_file.write(markdown.strip() + "\n\n---\n\n")


def _log_step(topic: str, title: str, thinking: str, answer: str, answer_lang: str = "") -> None:
    """把一次请求的思考内容与输出内容作为一个 Markdown 章节写入日志。"""
    thinking = (thinking or "").strip()
    answer = (answer or "").strip()
    parts = [
        f"## {title}",
        "",
        f"> 记录时间：{_now()}",
        "",
        "### 思考内容",
        "",
        _demote_headings(thinking) or "（接口未返回思考内容）",
        "",
        "### 输出内容",
        "",
    ]
    if answer_lang:
        # 用四个反引号包住，避免内容里自带的 ``` 提前闭合代码块
        parts += [f"````{answer_lang}", answer or "（空响应）", "````"]
    else:
        parts.append(_demote_headings(answer) or "（空响应）")
    _append_log(topic, "\n".join(parts))


def _log_warning(topic: str | None, message: str) -> None:
    """在终端和对应主题的 log 文件中记录运行时警告。"""
    line = f"[WARN] {message}"
    print(line, file=sys.stderr) #file=sys.stderr是标准错误流
    if topic:
        _append_log(topic, f"> **{line}**")


# noinspection bad-argument-type
def get_anthropic(topic):

    client = Anthropic(
        api_key=os.getenv('DEEPSEEK_API_KEY'),
        base_url="https://api.deepseek.com/anthropic",
    )
    messages = [{"role": "user", "content": topic}]

    with client.messages.stream(
            model="deepseek-flash",
            max_tokens=100000,
            system=prompt.mat_finder,
            messages=messages,
            output_config={"effort": "high"},
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 90}],
            tool_choice={"type": "tool", "name": "web_search"},
    ) as stream:
        response = stream.get_final_message()
        thinking_text = "".join(
            block.thinking for block in response.content if block.type == "thinking"
        )

        answer_text = "".join(
            block.text for block in response.content if block.type == "text"
        )
    _log_step(topic, "阶段 1 · 检索与素材整理", thinking_text, answer_text)
    return answer_text


# noinspection bad-argument-type
def get_openai(former_answer, topic):
    messages = [
        {"role": "system", "content": prompt.fake_mat_finder},
        {"role": "user", "content": topic},
        {"role": "assistant", "content": former_answer},
        {"role": "user", "content": prompt.resformat},
    ]
    client = OpenAI(
        api_key=os.getenv('DEEPSEEK_API_KEY'),
        base_url="https://api.deepseek.com/",
    )

    last_raw = None
    for attempt in range(MAX_JSON_RETRIES + 1):
        response = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
            response_format={"type": "json_object"},
            max_tokens=100000,
            tool_choice="none",
        )
        last_raw = response.choices[0].message.content
        thinking_text = response.choices[0].message.reasoning_content

        _log_step(
            topic,
            f"阶段 2 · JSON 整理（第 {attempt + 1} 次请求）",
            thinking_text,
            last_raw,
            answer_lang="json",
        )

        try:
            parsed = json.loads(last_raw)
            if not isinstance(parsed, dict):
                raise ValueError("JSON 顶层必须是对象")
            return last_raw
        except (TypeError, ValueError) as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            _log_warning(topic, f"JSON 解析失败（第 {attempt + 1} 次请求）：{error_message}")
            if attempt >= MAX_JSON_RETRIES:
                break
            messages.append({"role": "assistant", "content": last_raw or "（空响应）"})
            messages.append({
                "role": "user",
                "content": (
                    f"你上面的输出不是合法 JSON，解析报错：{error_message}。"
                    "请修正后重新输出完整 JSON，只输出 JSON 本身，"
                    "不要输出解释、Markdown 代码块或任何其他内容。"
                ),
            })

    return last_raw


def parse_sucai(raw_json: str, topic: str | None = None) -> str:
    """把 JSON 素材转成人类易读的纯文本"""
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        _log_warning(topic, f"素材 JSON 解析失败：{type(exc).__name__}: {exc}")
        return f"[解析失败] {exc}\n原始内容:\n{raw_json}"

    #它处理的情况是：json.loads() 成功了，但结果不是 JSON 对象。
    if not isinstance(data, dict):
        _log_warning(topic, f"素材 JSON 顶层不是对象：{type(data).__name__}")
        return (
            f"[解析失败] JSON 顶层必须是对象，实际为 {type(data).__name__}\n"
            f"原始内容:\n{raw_json}"
        )

    missing_fields = [field for field in KNOWN_FIELDS if field not in data]
    if missing_fields:
        _log_warning(topic, f"素材 JSON 缺少字段：{', '.join(missing_fields)}")

    unknown_fields = [field for field in data if field not in KNOWN_FIELDS]
    if unknown_fields:
        _log_warning(topic, f"素材 JSON 包含未知字段：{', '.join(unknown_fields)}")

    lines = []

    if "name" in data:
        lines.append(f"{data['name']}")
        lines.append("")

    if "tag" in data:
        lines.append(f"tags: \n  {', '.join(data['tag'])}")
        lines.append("")

    if "detail" in data:
        lines.append("detail:")
        for i, item in enumerate(data["detail"], 1):
            lines.append(f"{i}.{item.get('content', '')}")
            if "tags" in item:
                lines.append(f"tag: {' '.join(item['tags'])} \n")
        lines.append("")

    for key in ("transcend", "note", "cache"):
        if key in data:
            lines.append(f"{key}:")
            for item in data[key]:
                lines.append(f"  - {item}")
            lines.append("")

    # 兜底：如果 JSON 里有上面没覆盖的字段，也一并输出
    for k, v in data.items():
        if k not in KNOWN_FIELDS:
            lines.append(f"{k}: {v}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"

