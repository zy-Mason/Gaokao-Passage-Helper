# 单素材处理入口脚本：输入一个素材名，调用 AI 完成检索、整理并写入 素材/ 目录
import os

from tool import get_anthropic, get_file_object, get_openai, parse_sucai



topic = input("输入素材名：").strip()
# 素材名为空则直接退出
if not topic:
    print("素材名不能为空。")
    raise SystemExit(1)

# 根据素材名拼出输出路径
output_path = f"素材/{topic}.txt"
# 已存在同名素材时先确认，防止误覆盖已有结果，直接退出
if os.path.exists(output_path):
    answer = input(f"{output_path} 已存在，是否覆盖？(y/N)：").strip().lower()
    if answer != "y":
        print("已取消，未覆盖现有文件。")
        raise SystemExit(0)

# 第一步：让 Anthropic 兼容接口（带联网检索）收集素材，并写入 log/ 日志
analysis_text = get_anthropic(topic=topic)
# 第二步：让 OpenAI 兼容接口把检索结果整理成固定字段的 JSON
sucai_json = get_openai(former_answer=analysis_text, topic=topic)
# 第三步：把 JSON 转成易读纯文本；mode="w" 覆盖写入，目录不存在时会自动创建
# 原始 JSON 另存为 Markdown，方便直接阅读与手动修正
with get_file_object(f"log/{topic}json.md", mode="w") as file:
    file.write(f"# {topic} · 原始 JSON\n\n````json\n{sucai_json.strip()}\n````\n")
with get_file_object(output_path, mode="w") as output_file:
    output_file.write(parse_sucai(sucai_json, topic=topic))
