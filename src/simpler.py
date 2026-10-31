# 简化素材入口脚本：弹窗勾选 素材/ 里的素材，用 prompt.simpler 生成速览版，写入 简化素材/
# 流程：运行 -> tk 弹窗勾选素材、选择是否覆盖 -> 窗口内流式显示思考与回答（终端同步打印）
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from tkinter import messagebox, ttk

from openai import OpenAI

import prompt
from tool import get_file_object

MAT_DIR = "素材"
OUT_DIR = "简化素材"
MODEL = os.getenv("SIMPLER_MODEL", "deepseek-flash")
BASE_URL = os.getenv("SIMPLER_BASE_URL", "https://api.deepseek.com/")
MAX_TOKENS = 32000
POLL_INTERVAL_MS = 60

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


def _center(root: tk.Tk, width: int, height: int) -> None:
    """把窗口摆到屏幕中间偏上，避免默认位置跑到屏幕角落。"""
    screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
    x = max((screen_width - width) // 2, 0)
    y = max((screen_height - height) // 3, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")


def _delta_text(delta, *names: str) -> str:
    """按字段名依次取增量文本，各家兼容接口对思考内容的叫法不一致。"""
    for name in names:
        value = getattr(delta, name, None)
        if value:
            return value
    return ""


def simplify(
        material: str,
        name: str,
        on_delta: Callable[[str, str], None] | None = None,
) -> str:
    """用 prompt.simpler 把素材压成速览版；思考与回答实时打印并回调给窗口。"""
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=BASE_URL)
    parts: list[str] = []
    answering = False
    print(f"{DIM}── {name} · 思考 ──{RESET}")
    # reasoning_effort 与 extra_body 里的 thinking 是 DeepSeek 的写法，换别家可删掉
    with client.chat.completions.create(
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
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = _delta_text(delta, "reasoning_content", "reasoning")
            if reasoning:
                print(f"{DIM}{reasoning}{RESET}", end="", flush=True)
                if on_delta:
                    on_delta("thinking", reasoning)
            content = _delta_text(delta, "content")
            if content:
                if not answering:
                    print(f"\n{DIM}── 思考结束 ──{RESET}\n{CYAN}── 输出 ──{RESET}")
                    answering = True
                parts.append(content)
                print(content, end="", flush=True)
                if on_delta:
                    on_delta("answer", content)
    print()
    return "".join(parts)


def run(names: list[str], overwrite: bool, emit: Callable[[str, tuple], None]) -> int:
    """逐个简化素材并写入 简化素材/，进度通过 emit(事件名, 数据) 推给窗口。"""
    succeeded = skipped = 0
    failed: list[str] = []
    interrupted = False

    for index, name in enumerate(names, 1):
        output_path = _output_path(name)
        if os.path.exists(output_path) and not overwrite:
            print(f"[跳过] {name}：{output_path} 已存在（未勾选覆盖）")
            emit("skip", (name, output_path))
            skipped += 1
            continue

        emit("start", (index, len(names), name))
        print(f"[{index}/{len(names)}] 开始简化 {name}")
        start = time.perf_counter()
        try:
            with get_file_object(f"{MAT_DIR}/{name}.txt", mode="r") as material_file:
                material = material_file.read()
            answer = simplify(
                material,
                name,
                on_delta=lambda kind, text: emit("delta", (kind, text)),
            ).strip()
            if not answer:
                raise ValueError("接口返回了空内容")
            # get_file_object 会自动创建 简化素材/ 目录；mode="w" 覆盖写入
            with get_file_object(output_path, mode="w") as output_file:
                output_file.write(answer + "\n")
        except KeyboardInterrupt:
            print("\n[WARN] 已被用户中断，已生成的简化素材保留。", file=sys.stderr)
            interrupted = True
            break
        except Exception as exc:
            print(f"[ERROR] {name} 简化失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            emit("error", (name, f"{type(exc).__name__}: {exc}"))
            failed.append(name)
            continue

        elapsed = time.perf_counter() - start
        print(f"[完成] {name} → {output_path}（{elapsed:.1f} 秒）")
        emit("done", (name, output_path, elapsed))
        succeeded += 1

    summary = f"完成：成功 {succeeded} 个，跳过 {skipped} 个，失败 {len(failed)} 个"
    print(f"\n{summary}")
    if failed:
        print(f"失败列表：{failed}")
    emit("summary", (summary, failed))
    return 1 if interrupted or failed else 0


class SimplerApp:
    """一个窗口走完：勾选素材 -> 生成简化素材 -> 查看流式结果。"""

    def __init__(self, root: tk.Tk, materials: list[str]) -> None:
        self.root = root
        self.materials = materials
        # 默认只勾选还没生成过简化素材的项，已有的留给用户自己决定
        self.checked = {
            name: tk.BooleanVar(master=root, value=not os.path.exists(_output_path(name)))
            for name in materials
        }
        self.overwrite_var = tk.BooleanVar(master=root, value=False)
        self.events: queue.Queue = queue.Queue()

        self.started = False
        self.running = False
        self.exit_code = 0
        self.total = 0
        self.completed = 0
        self.answering = False

        self.title_font = tkfont.nametofont("TkDefaultFont").copy()
        self.title_font.configure(size=11, weight="bold")
        self.text_font = tkfont.nametofont("TkDefaultFont").copy()
        self.text_font.configure(size=10)

        root.title("简化素材")
        _center(root, 460, 540)
        root.minsize(380, 420)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.select_frame = self._build_select()
        self.output_frame = self._build_output()
        self.select_frame.pack(fill="both", expand=True)

    def _build_select(self) -> tk.Frame:
        """勾选视图：素材列表 + 覆盖开关 + 操作按钮。"""
        frame = tk.Frame(self.root)

        header = tk.Frame(frame, padx=12, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="选择要简化的素材", font=self.title_font).pack(anchor="w")
        tk.Label(header, text=f"来源：{os.path.abspath(MAT_DIR)}", fg="#666").pack(anchor="w")

        body = tk.Frame(frame, padx=12)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        list_frame = tk.Frame(canvas)
        list_frame.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=list_frame, anchor="nw")
        canvas.bind(
            "<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width)
        )
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def on_mouse_wheel(event: tk.Event) -> None:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        canvas.bind_all("<MouseWheel>", on_mouse_wheel)

        for name in self.materials:
            exists = os.path.exists(_output_path(name))
            tk.Checkbutton(
                list_frame,
                text=f"{name}（已有简化素材）" if exists else name,
                variable=self.checked[name],
                fg="#888" if exists else None,
                anchor="w",
            ).pack(fill="x", anchor="w")

        options = tk.Frame(frame, padx=12, pady=8)
        options.pack(fill="x")
        tk.Checkbutton(
            options,
            text="覆盖已存在的同名简化素材",
            variable=self.overwrite_var,
        ).pack(anchor="w")

        buttons = tk.Frame(frame, padx=12, pady=10)
        buttons.pack(fill="x")
        tk.Button(buttons, text="全选", width=8, command=lambda: self._select_all(True)).pack(
            side="left"
        )
        tk.Button(buttons, text="全不选", width=8, command=lambda: self._select_all(False)).pack(
            side="left", padx=(8, 0)
        )
        tk.Button(buttons, text="取消", width=8, command=self.on_close).pack(side="right")
        tk.Button(buttons, text="开始简化", width=10, command=self.start_run).pack(
            side="right", padx=(0, 8)
        )
        return frame

    def _build_output(self) -> tk.Frame:
        """结果视图：流式显示思考与回答，底部是进度与状态。"""
        frame = tk.Frame(self.root)

        header = tk.Frame(frame, padx=12, pady=8)
        header.pack(fill="x")
        tk.Label(header, text="生成结果", font=self.title_font).pack(anchor="w")
        tk.Label(header, text="灰色为思考内容，黑色为回答；终端同步打印完整过程", fg="#666").pack(
            anchor="w"
        )

        body = tk.Frame(frame, padx=12)
        body.pack(fill="both", expand=True)
        self.output_text = tk.Text(
            body,
            wrap="word",
            font=self.text_font,
            padx=8,
            pady=8,
            spacing1=2,
            spacing3=2,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#ddd",
            state="disabled",
        )
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=scrollbar.set)
        self.output_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.output_text.tag_configure("meta", foreground="#3b6ea5")
        self.output_text.tag_configure("thinking", foreground="#8a8a8a")
        self.output_text.tag_configure("answer", foreground="#111111")
        self.output_text.tag_configure("error", foreground="#c0392b")

        footer = tk.Frame(frame, padx=12, pady=10)
        footer.pack(fill="x")
        self.status_var = tk.StringVar(master=self.root, value="准备开始")
        tk.Label(footer, textvariable=self.status_var, fg="#444").pack(anchor="w")
        bar = tk.Frame(footer)
        bar.pack(fill="x", pady=(6, 0))
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=1)
        self.progress.pack(side="left", fill="x", expand=True)
        tk.Button(bar, text="关闭", width=8, command=self.on_close).pack(
            side="right", padx=(8, 0)
        )
        return frame

    def _select_all(self, value: bool) -> None:
        for var in self.checked.values():
            var.set(value)

    def start_run(self) -> None:
        """校验选择后切到结果视图，起后台线程跑批，主线程只负责渲染。"""
        names = [name for name in self.materials if self.checked[name].get()]
        if not names:
            messagebox.showwarning("未选择素材", "请至少勾选一个素材。", parent=self.root)
            return

        self.started = True
        self.running = True
        self.total = len(names)
        self.completed = 0
        self.progress.configure(maximum=self.total, value=0)
        self.status_var.set(f"准备简化 {self.total} 个素材…")
        self._append_text(f"模型：{MODEL} ｜ 提示词：prompt.simpler ｜ 共 {self.total} 个素材\n\n")

        self.select_frame.pack_forget()
        self.output_frame.pack(fill="both", expand=True)
        _center(self.root, 780, 640)
        self.root.title("简化素材 · 生成中")

        print(f"模型：{MODEL} ｜ 提示词：prompt.simpler ｜ 本次 {len(names)} 个素材")
        threading.Thread(
            target=self._run_batch,
            args=(names, self.overwrite_var.get()),
            daemon=True,
        ).start()
        self.root.after(POLL_INTERVAL_MS, self._poll_events)

    def _run_batch(self, names: list[str], overwrite: bool) -> None:
        """后台线程：只跑接口与写文件，结果全部通过队列交给主线程。"""
        code = 1
        try:
            code = run(names, overwrite, self._emit)
        except Exception as exc:  # 兜底，避免线程静默退出
            self._emit("error", ("批量执行", f"{type(exc).__name__}: {exc}"))
        finally:
            self._emit("finished", (code,))

    def _emit(self, event: str, payload: tuple) -> None:
        """把（事件名, 数据）打包成一个元组入队；不能直接传 Queue.put，
        否则第二个参数会被当成 put(block=...)，数据就丢了。"""
        self.events.put((event, payload))

    def _poll_events(self) -> None:
        """主线程定时把队列里的事件刷到界面上。"""
        try:
            while True:
                message = self.events.get_nowait()
                if not isinstance(message, tuple) or len(message) != 2:
                    print(f"[WARN] 丢弃异常事件：{message!r}", file=sys.stderr)
                    continue
                event, payload = message
                self._handle_event(event, payload)
        except queue.Empty:
            pass
        finally:
            # 无论本轮处理是否出错，都要继续轮询，否则界面会静默停更
            if self.running:
                self.root.after(POLL_INTERVAL_MS, self._poll_events)

    def _handle_event(self, event: str, payload: tuple) -> None:
        if event == "start":
            index, total, name = payload
            self.answering = False
            divider = "\n" if index > 1 else ""
            self._append_text(f"{divider}── {index}/{total} · {name} ──\n", "meta")
            self.status_var.set(f"正在简化 {index}/{total} · {name}")
        elif event == "delta":
            kind, text = payload
            if kind == "answer" and not self.answering:
                self.answering = True
                self._append_text("\n")
            self._append_text(text, "thinking" if kind == "thinking" else "answer")
        elif event == "skip":
            name, path = payload
            self._append_text(f"[跳过] {name}：{path} 已存在（未勾选覆盖）\n", "meta")
            self._advance_progress()
        elif event == "error":
            name, message = payload
            self._append_text(f"[ERROR] {name} 简化失败：{message}\n", "error")
            self._advance_progress()
        elif event == "done":
            name, path, elapsed = payload
            self._append_text(f"\n[完成] {name} → {path}（{elapsed:.1f} 秒）\n", "meta")
            self._advance_progress()
        elif event == "summary":
            summary, failed = payload
            self._append_text(f"\n{summary}\n", "meta")
            if failed:
                self.status_var.set(f"{summary}；失败：{', '.join(failed)}")
            else:
                self.status_var.set(summary)
        elif event == "finished":
            self.running = False
            self.exit_code = payload[0]
            self.root.title("简化素材 · 已完成")

    def _advance_progress(self) -> None:
        self.completed = min(self.completed + 1, self.total)
        self.progress.configure(value=self.completed)

    def _append_text(self, text: str, tag: str = "answer") -> None:
        """往只读文本框里追加一段内容并滚到末尾。"""
        widget = self.output_text
        widget.configure(state="normal")
        widget.insert("end", text, tag)
        widget.configure(state="disabled")
        widget.see("end")

    def on_close(self) -> None:
        """关窗前确认，避免任务跑一半被误关。"""
        if self.running:
            if not messagebox.askyesno(
                "任务进行中",
                "简化任务还在进行，确定要退出吗？\n未完成的素材不会保存。",
                parent=self.root,
            ):
                return
            self.running = False
            self.exit_code = self.exit_code or 1
        self.root.destroy()


def main() -> int:
    """读取素材目录，弹出窗口完成任务选择、生成与结果查看。"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("[ERROR] 未设置 DEEPSEEK_API_KEY 环境变量", file=sys.stderr)
        return 1

    materials = list_materials()
    if not materials:
        print(f"[ERROR] {MAT_DIR}/ 下没有 .txt 素材可简化", file=sys.stderr)
        return 1

    root = tk.Tk()
    app = SimplerApp(root, materials)
    root.mainloop()
    if not app.started:
        print("已取消，未生成任何简化素材。")
    return app.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
