from anthropic import Anthropic
from openai import OpenAI
import os
import prompt
import json

def get_file_object(file_path: str,mode :str="a",encoding="utf-8"):
    """
    传入一个 txt 文件的路径字符串。
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


# noinspection bad-argument-type
def get_anthropic(zhuti):

    client = Anthropic(
        api_key=os.getenv('DEEPSEEK_API_KEY'),
        base_url="https://api.deepseek.com/anthropic",
    )
    messages = [{"role": "user", "content": zhuti}]

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
    log=get_file_object(f"log/{zhuti}.txt", "a", encoding="utf-8")
    log.write(f"{zhuti} \n ,思考内容 \n {thinking_text}\n\n 输出内容{answer_text}\n")
    log.close()
    return answer_text


# noinspection bad-argument-type
def get_openai(former_answer,zhuti):
    messages=[{"role":"system","content":prompt.fake_mat_finder},
              {"role":"user","content":zhuti},
              {"role":"assistant","content":former_answer,},
              {"role":"user","content":prompt.resformat}
              ]
    client = OpenAI(api_key=os.getenv('DEEPSEEK_API_KEY'),
        base_url="https://api.deepseek.com/",)
    response = client.chat.completions.create(
        model="deepseek-flash",
        messages=messages,
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking":{"type":"enabled"}},
        response_format={"type":"json_object"},
        max_tokens=100000,
        tool_choice="none"

    )
    sucai_raw = response.choices[0].message.content
    thinking_text = response.choices[0].message.reasoning_content
    log=open(f"log/{zhuti}.txt", "a", encoding="utf-8")
    log.write(f"\n\n 整理 \n 思考内容{thinking_text}\n\n 输出内容{sucai_raw}\n")
    log.write("-----------------------------------------------------")
    log.close()
    return sucai_raw


def parse_sucai(sucai_str: str) -> str:
    """把 JSON 素材转成人类易读的纯文本（无 markdown 语法）"""
    try:
        data = json.loads(sucai_str)
    except json.JSONDecodeError as e:
        return f"[解析失败] {e}\n原始内容:\n{sucai_str}"

    lines = []

    if "name" in data:
        lines.append(f"{data['name']}")
        lines.append("")

    if "tag" in data:
        lines.append(f"tags: \n  {', '.join(data['tag'])}")
        lines.append("")

    if "summary" in data:
        lines.append(f"summary:  \n {data['summary']}")
        lines.append("")

    if "detail" in data:
        lines.append("detail:")
        for i, item in enumerate(data["detail"], 1):
            lines.append(f"{i}.{item.get('content', '')}")
            if "tags" in item:
                lines.append(f"tag: {''.join(item['tags'])} \n")
        lines.append("")

    for key in ("transcend", "note", "cache"):
        if key in data:
            lines.append(f"{key}:")
            for item in data[key]:
                lines.append(f"  - {item}")
            lines.append("")

    # 兜底：如果 JSON 里有上面没覆盖的字段，也一并输出
    known = {"name", "tag", "summary", "detail", "transcend", "note", "cache"}
    for k, v in data.items():
        if k not in known:
            lines.append(f"{k}: {v}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"

