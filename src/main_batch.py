# 批量素材处理入口脚本：一次输入多个素材名，并发调用 AI 完成检索、整理并写入 素材/ 目录
import asyncio
import os

from tool import get_anthropic, get_file_object, get_openai, parse_sucai

# 同时处理的最大素材数，可用环境变量 BATCH_CONCURRENCY 覆盖，避免并发过高触发接口限流
MAX_CONCURRENCY = 50

# 并发处理单个素材
async def process_topic(topic: str, semaphore: asyncio.Semaphore) -> bool:
    """并发处理单个素材，返回是否成功；单个素材出错不影响其他素材。"""
    async with semaphore:
        print(f"开始执行 {topic}")
        try:
            # 第一步：让 Anthropic 兼容接口（带联网检索）收集并整理素材，同时写入 log/ 日志
            analysis_text = await get_anthropic(topic=topic)
            # 第二步：让 OpenAI 兼容接口把检索结果整理成固定字段的 JSON
            sucai_json = await get_openai(former_answer=analysis_text, topic=topic)
            # 第三步：把 JSON 转成易读纯文本，mode="w" 覆盖写入，目录不存在时自动创建
            with get_file_object(f"素材/{topic}.txt", mode="w") as output_file:
                output_file.write(parse_sucai(sucai_json, topic=topic))
        except Exception as exc:
            print(f"[ERROR] {topic} 处理失败：{type(exc).__name__}: {exc}")
            return False
        print(f"[完成] {topic}")
        return True

# 返回失败素材列表
async def run_batch(pending: list[str]) -> list[str]:
    """并发跑完所有待处理素材，返回失败素材列表。"""
    # 限制并发数为 MAX_CONCURRENCY
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    # results 是一个布尔值列表，表示每个素材是否处理成功
    results = await asyncio.gather(
        *(process_topic(topic, semaphore) for topic in pending)
    )
    return [topic for topic, ok in zip(pending, results) if not ok]


# 读取素材名列表：多个素材用空格分割，空输入直接退出
topics_input = input("输入一组素材名，用空格分割：").strip()
topics = topics_input.split()
if not topics:
    print("没有输入任何素材名。")
    raise SystemExit(1)

# 执行前先列出待处理素材，确认后才继续，避免误操作
print("即将整理这些素材，确认请输入 y 回车")
print(topics)
confirm = input().strip().lower()
if confirm != "y":
    print("已取消。")
    raise SystemExit(0)

# 检查哪些素材已存在，统一询问一次是否覆盖（默认不覆盖）
existing = [topic for topic in topics if os.path.exists(f"素材/{topic}.txt")]
overwrite_existing = False
if existing:
    print(f"以下素材已存在：{existing}")
    overwrite_existing = input("是否覆盖已存在的素材？(y/N)：").strip().lower() == "y"

# 先筛出需要处理的素材；已存在且用户选择不覆盖的直接跳过

#pending: 要处理的素材列表
#skipped: 跳过的素材列表


pending = []
skipped = []
for topic in topics:
    output_path = f"素材/{topic}.txt"
    if os.path.exists(output_path) and not overwrite_existing:
        print(f"跳过 {topic}：{output_path} 已存在")
        skipped.append(topic)
    else:
        pending.append(topic)

# 并发处理待处理素材，串行输入交互结束后才开始跑事件循环
failed = asyncio.run(run_batch(pending)) if pending else []

# 汇总结果：成功数 = 总数 - 跳过数 - 失败数；有失败时以非零退出码结束
succeeded = len(topics) - len(skipped) - len(failed)
print(f"完成：成功 {succeeded} 个，跳过 {len(skipped)} 个，失败 {len(failed)} 个")
if failed:
    print(f"失败列表：{failed}")
    raise SystemExit(1)
