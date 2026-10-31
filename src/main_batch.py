import os

from tool import get_anthropic, get_file_object, get_openai, parse_sucai


topics_input = input("输入一组素材名，用空格分割：").strip()
topics = topics_input.split()
if not topics:
    print("没有输入任何素材名。")
    raise SystemExit(1)

print("即将整理这些素材，确认请输入 y 回车")
print(topics)
confirm = input().strip().lower()
if confirm != "y":
    print("已取消。")
    raise SystemExit(0)

existing = [topic for topic in topics if os.path.exists(f"素材/{topic}.txt")]
overwrite_existing = False
if existing:
    print(f"以下素材已存在：{existing}")
    overwrite_existing = input("是否覆盖已存在的素材？(y/N)：").strip().lower() == "y"

failed = []
skipped = []
for topic in topics:
    output_path = f"素材/{topic}.txt"
    if os.path.exists(output_path) and not overwrite_existing:
        print(f"跳过 {topic}：{output_path} 已存在")
        skipped.append(topic)
        continue

    print(f"开始执行 {topic}")
    try:
        analysis_text = get_anthropic(topic=topic)
        sucai_json = get_openai(former_answer=analysis_text, topic=topic)
        with get_file_object(output_path, mode="w") as output_file:
            output_file.write(parse_sucai(sucai_json, topic=topic))
    except Exception as exc:
        print(f"[ERROR] {topic} 处理失败：{type(exc).__name__}: {exc}")
        failed.append(topic)

succeeded = len(topics) - len(skipped) - len(failed)
print(f"完成：成功 {succeeded} 个，跳过 {len(skipped)} 个，失败 {len(failed)} 个")
if failed:
    print(f"失败列表：{failed}")
    raise SystemExit(1)
