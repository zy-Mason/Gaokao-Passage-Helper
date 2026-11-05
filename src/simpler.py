# 简化素材入口脚本：终端里选择 素材/ 里的素材，用 prompt.simpler 生成速览版，写入 简化素材/
# 流程：运行 -> 列出素材、输入编号并选择是否覆盖 -> 并发请求，每个素材结束后整段打印思考与回答
import asyncio
import os
import sys
import time

from openai import AsyncOpenAI

import prompt
from tool import get_file_object

MAT_DIR = "素材"
OUT_DIR = "简化素材"
MODEL = os.getenv("SIMPLER_MODEL", "deepseek-flash")
BASE_URL = os.getenv("SIMPLER_BASE_URL", "https://api.deepseek.com/")
MAX_TOKENS = 32000
# 同时简化的最大素材数，可用环境变量 SIMPLER_CONCURRENCY 覆盖，避免并发过高触发接口限流
MAX_CONCURRENCY = int(os.getenv("SIMPLER_CONCURRENCY", "3"))

# 只在真正的终端里上色；重定向到文件或设置了 NO_COLOR 时输出纯文本
USE_COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")
DIM, CYAN, RESET = ("\033[2m", "\033[36m", "\033[0m") if USE_COLOR else ("", "", "")


def _output_path(name: str) -> str:
    """素材名对应的简化素材路径，与 素材/ 目录保持同名。"""
    return f"{OUT_DIR}/{name}.txt"


def list_materials() -> list[str]:
    """列出 素材/ 目录下的 .txt 素材名（去掉扩展名），按名称排序。"""
    if not os.path.isdir(MAT_DIR):
        return []
    return sorted(
        filename[:-4] for filename in os.listdir(MAT_DIR) if filename.endswith(".txt")
    )


def _delta_text(delta, *names: str) -> str:
    """按字段名依次取增量文本，各家兼容接口对思考内容的叫法不一致。"""
    for name in names:
        value = getattr(delta, name, None)
        if value:
            return value
    return ""


async def simplify(client: AsyncOpenAI, material: str, name: str) -> str:
    """用 prompt.simpler 把素材压成速览版；思考与回答先缓存，跑完再整段打印。"""
    thinking: list[str] = []
    parts: list[str] = []
    # reasoning_effort 与 extra_body 里的 thinking 是 DeepSeek 的写法，换别家可删掉
    async with client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": prompt.simpler},
                {"role": "user", "content": material},
            ],
            stream=True,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
            max_tokens=MAX_TOKENS,
    ) as stream:
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = _delta_text(delta, "reasoning_content", "reasoning")
            if reasoning:
                thinking.append(reasoning)
            content = _delta_text(delta, "content")
            if content:
                parts.append(content)

    # 多个素材同时在跑，边收边打印会让几路输出交错；这里缓存到本素材结束，再整段打印
    answer = "".join(parts)
    lines: list[str] = []
    if thinking:
        lines += [f"{DIM}── {name} · 思考 ──{RESET}", f"{DIM}{''.join(thinking)}{RESET}"]
    lines += [f"{CYAN}── {name} · 输出 ──{RESET}", answer]
    print("\n".join(lines))
    return answer


async def process(
        client: AsyncOpenAI,
        semaphore: asyncio.Semaphore,
        name: str,
        index: int,
        total: int,
) -> bool:
    """并发简化单个素材并写入 简化素材/，返回是否成功；单个素材出错不影响其他素材。"""
    async with semaphore:
        output_path = _output_path(name)
        print(f"[{index}/{total}] 开始简化 {name}")
        start = time.perf_counter()
        try:
            with get_file_object(f"{MAT_DIR}/{name}.txt", mode="r") as material_file:
                material = material_file.read()
            answer = (await simplify(client, material, name)).strip()
            if not answer:
                raise ValueError("接口返回了空内容")
            # get_file_object 会自动创建 简化素材/ 目录；mode="w" 覆盖写入
            with get_file_object(output_path, mode="w") as output_file:
                output_file.write(answer + "\n")
        except Exception as exc:
            print(f"[ERROR] {name} 简化失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            return False

        elapsed = time.perf_counter() - start
        print(f"[完成] {name} → {output_path}（{elapsed:.1f} 秒）")
        return True


async def run(names: list[str], overwrite: bool) -> int:
    """并发简化素材并写入 简化素材/，返回退出码。"""
    # 先筛出需要处理的素材；已存在且未选择覆盖的直接跳过
    pending: list[str] = []
    skipped = 0
    for name in names:
        if os.path.exists(_output_path(name)) and not overwrite:
            print(f"[跳过] {name}：{_output_path(name)} 已存在（未选择覆盖）")
            skipped += 1
        else:
            pending.append(name)

    failed: list[str] = []
    if pending:
        client = AsyncOpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=BASE_URL)
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        results = await asyncio.gather(
            *(
                process(client, semaphore, name, index, len(pending))
                for index, name in enumerate(pending, 1)
            )
        )
        failed = [name for name, ok in zip(pending, results) if not ok]
        await client.close()

    succeeded = len(pending) - len(failed)
    summary = f"完成：成功 {succeeded} 个，跳过 {skipped} 个，失败 {len(failed)} 个"
    print(f"\n{summary}")
    if failed:
        print(f"失败列表：{failed}")
    return 1 if failed else 0


def parse_selection(raw: str, materials: list[str]) -> list[str]:
    """把 "1 3 5"、"1,3,5"、"a" 解析成素材名列表；编号非法时抛 ValueError。"""
    if raw.lower() in ("a", "all"):
        return list(materials)
    names: list[str] = []
    for token in raw.replace("，", " ").replace(",", " ").split():
        if not token.isdigit() or not 1 <= int(token) <= len(materials):
            raise ValueError(f"无效编号 {token}")
        name = materials[int(token) - 1]
        if name not in names:
            names.append(name)
    return names


def choose(materials: list[str]) -> list[str]:
    """打印素材清单并读取选择；直接回车等于只处理还没有简化素材的项。"""
    print(f"素材来源：{os.path.abspath(MAT_DIR)} ｜ 模型：{MODEL}")
    default: list[str] = []
    for index, name in enumerate(materials, 1):
        exists = os.path.exists(_output_path(name))
        mark = "（已有简化素材）" if exists else ""
        print(f"  {index:>2}. {name}{mark}")
        if not exists:
            default.append(name)

    hint = "输入要简化的编号（空格或逗号分隔，a=全部，直接回车=只处理还没有简化素材的项）："
    while True:
        raw = input(hint).strip()
        if not raw:
            return default
        try:
            names = parse_selection(raw, materials)
        except ValueError as exc:
            print(f"{exc}，请重新输入。")
            continue
        if not names:
            print("没有选中任何素材，请重新输入。")
            continue
        return names


def main() -> int:
    """列出素材、读取选择，然后并发生成简化素材。"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("[ERROR] 未设置 DEEPSEEK_API_KEY 环境变量", file=sys.stderr)
        return 1

    materials = list_materials()
    if not materials:
        print(f"[ERROR] {MAT_DIR}/ 下没有 .txt 素材可简化", file=sys.stderr)
        return 1

    names = choose(materials)
    if not names:
        print("所选素材都已有简化素材；如需重做，请重新运行并选 a 或输入编号。")
        return 0

    # 已有同名简化素材时统一询问一次是否覆盖（默认不覆盖，逐个跳过）
    existing = [name for name in names if os.path.exists(_output_path(name))]
    overwrite = False
    if existing:
        print(f"以下素材已有简化素材：{existing}")
        overwrite = input("是否覆盖已存在的简化素材？(y/N)：").strip().lower() == "y"

    print(
        f"模型：{MODEL} ｜ 提示词：prompt.simpler ｜ 本次 {len(names)} 个素材 ｜ 并发 {MAX_CONCURRENCY}"
    )
    try:
        return asyncio.run(run(names, overwrite))
    except KeyboardInterrupt:
        print("\n[WARN] 已被用户中断，已生成的简化素材保留。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
