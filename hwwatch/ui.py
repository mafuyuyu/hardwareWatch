# -*- coding: utf-8 -*-
"""Tkinter UI: live timeline, filters, detail pane, exports."""
from __future__ import annotations

import datetime
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import classify, config, exporter, winapi

KIND_CHOICES = [
    ("全部", ""),
    ("硬件接入", "arrival"),
    ("硬件移除", "removal"),
    ("设备配置", "device_config"),
    ("设备异常", "device_problem"),
    ("驱动安装", "driver_install"),
    ("驱动服务", "driver_service"),
    ("驱动变更", "driver_change"),
    ("驱动加载失败", "driver_error"),
    ("Windows 更新", "windows_update"),
    ("声音标记", "marker"),
    ("疑似异常", "alert"),
]

RANGE_CHOICES = [
    ("今天", "today"),
    ("近 7 天", "7d"),
    ("近 30 天", "30d"),
    ("全部", "all"),
]


def _clue_brief(raw):
    try:
        clues = json.loads(raw or "[]")
    except ValueError:
        return ""
    if isinstance(clues, list) and clues and isinstance(clues[0], dict):
        return clues[0].get("text", "")
    return ""


class MainWindow:
    def __init__(self, root, app, icon_path=""):
        self.root = root
        self.app = app
        self.store = app.store
        self.settings = app.settings
        self._last_id = 0
        self._filtered = False
        self._search_job = None
        self._full_dirty = True
        self._shown = True
        self._last_status = 0.0
        self._build(icon_path)
        self.root.after(150, self._pump)
        self.root.after(600, self._tick)
        self.root.after(900, self._status_tick)
        self.root.after(1000, self._load_initial)

    # -- layout ------------------------------------------------------------
    def _build(self, icon_path):
        root = self.root
        root.title("HwWatch · 硬件与驱动事件记录器")
        root.geometry("1200x760+90+70")
        root.minsize(980, 620)
        if icon_path and os.path.exists(icon_path):
            try:
                root.iconbitmap(icon_path)
            except Exception:
                pass
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Treeview", rowheight=26, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 9, "bold"))

        top = ttk.Frame(root, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        ttk.Label(
            top, text="HwWatch", font=("Microsoft YaHei UI", 14, "bold")
        ).pack(side="left")
        ttk.Label(
            top,
            text="  实时记录硬件接入/移除、驱动安装与设备异常",
            foreground="#66707d",
        ).pack(side="left")

        self.btn_mark = ttk.Button(
            top, text="标记：我听到了 (Ctrl+Alt+M)",
            style="Accent.TButton", command=self.app.mark_sound,
        )
        self.btn_mark.pack(side="right", padx=(6, 0))
        self.btn_pause = ttk.Button(top, text="暂停提醒", command=self.app.toggle_pause)
        self.btn_pause.pack(side="right", padx=6)
        ttk.Button(top, text="导出 HTML", command=self.export_html).pack(side="right", padx=6)
        ttk.Button(top, text="专项复盘", command=self.app.run_forensics).pack(side="right", padx=6)
        ttk.Button(top, text="导出 CSV", command=self.export_csv).pack(side="right", padx=6)

        self.banner = tk.Label(
            root, anchor="w", justify="left", padx=10, pady=4,
            bg="#fff4e5", fg="#8a4b00",
            text="当前为普通权限：驱动安装等系统级事件可能记录不全。右键以管理员身份运行可获得完整记录。",
        )
        if not winapi.is_admin():
            self.banner.pack(fill="x")

        flt = ttk.Frame(root, padding=(10, 6))
        flt.pack(fill="x")
        ttk.Label(flt, text="搜索").pack(side="left")
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *a: self._schedule_search())
        entry = ttk.Entry(flt, textvariable=self.var_search, width=32)
        entry.pack(side="left", padx=(6, 12))
        ttk.Label(flt, text="类型").pack(side="left")
        self.var_kind = tk.StringVar(value="全部")
        combo = ttk.Combobox(
            flt, textvariable=self.var_kind, width=12, state="readonly",
            values=[c[0] for c in KIND_CHOICES],
        )
        combo.pack(side="left", padx=(6, 12))
        combo.bind("<<ComboboxSelected>>", lambda e: self._filter_changed())
        ttk.Label(flt, text="范围").pack(side="left")
        self.var_range = tk.StringVar(value="近 7 天")
        rcombo = ttk.Combobox(
            flt, textvariable=self.var_range, width=8, state="readonly",
            values=[c[0] for c in RANGE_CHOICES],
        )
        rcombo.pack(side="left", padx=(6, 12))
        rcombo.bind("<<ComboboxSelected>>", lambda e: self._filter_changed())
        self.var_problem = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            flt, text="只看异常", variable=self.var_problem,
            command=self._filter_changed,
        ).pack(side="left", padx=(2, 12))
        self.btn_deep = ttk.Button(
            flt, text=self._deep_label(), command=self.toggle_deep_audit
        )
        self.btn_deep.pack(side="right", padx=6)
        ttk.Button(flt, text="添加备注", command=self.add_note).pack(side="right")
        ttk.Button(flt, text="打开数据目录", command=self.open_data_dir).pack(
            side="right", padx=6
        )
        self.var_count = tk.StringVar(value="")
        ttk.Label(flt, textvariable=self.var_count, foreground="#66707d").pack(
            side="right", padx=10
        )

        paned = ttk.PanedWindow(root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        tree_frame = ttk.Frame(paned)
        columns = ("time", "kind", "name", "ids", "driver", "clues", "note")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "time": ("时间", 130, "w"),
            "kind": ("类型", 92, "center"),
            "name": ("设备", 250, "w"),
            "ids": ("VID / PID / 实例", 190, "w"),
            "driver": ("驱动", 170, "w"),
            "clues": ("触发线索", 260, "w"),
            "note": ("备注", 130, "w"),
        }
        for key, (text, width, anchor) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=(key in ("name", "clues")))
        self.tree.tag_configure("sev3", background="#fdeaea")
        self.tree.tag_configure("sev2", background="#fff4e5")
        self.tree.tag_configure("marker", background="#eef7ee")
        self.tree.tag_configure("alert", background="#fdeaea")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        paned.add(tree_frame, weight=4)

        detail_frame = ttk.Frame(paned)
        self.detail = tk.Text(
            detail_frame, height=10, wrap="word", font=("Microsoft YaHei UI", 9),
            bg="#fbfcfd", relief="flat", padx=10, pady=8,
        )
        dsb = ttk.Scrollbar(detail_frame, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=dsb.set)
        self.detail.pack(side="left", fill="both", expand=True)
        dsb.pack(side="right", fill="y")
        self.detail.insert("1.0", "选择一条记录即可查看设备、驱动与触发线索。\n\n"
                           "提示：按 Ctrl+Alt+M 或点击右上角按钮，把你听到的提示音标记下来，报告中会自动关联前后 30 秒的事件。")
        self.detail.configure(state="disabled")
        paned.add(detail_frame, weight=2)

        status = ttk.Frame(root, padding=(10, 3, 10, 6))
        status.pack(fill="x")
        self.var_status = tk.StringVar(value="正在启动…")
        ttk.Label(status, textvariable=self.var_status, foreground="#48505c").pack(
            side="left"
        )
        ttk.Label(
            status,
            text="提示：听到提示音却找不到来源时，按 Ctrl+Alt+M 标记，报告里会自动关联前后 30 秒的事件。",
            foreground="#8a94a3",
        ).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

    # -- queue / timers ----------------------------------------------------
    def _pump(self):
        try:
            while True:
                msg = self.app.ui_queue.get_nowait()
                kind = msg[0]
                if kind == "show":
                    self.show()
                elif kind == "quit":
                    self.quit()
                    return
                elif kind == "export":
                    self.export_html()
                elif kind == "pause":
                    self._apply_pause(bool(msg[1]))
                elif kind == "marker":
                    self._flash_status("已记录声音标记，正在关联附近事件…")
                elif kind == "forensics_done":
                    if messagebox.askyesno(
                        "专项复盘", "报告已生成：\n%s\n\n现在打开吗？" % msg[1]
                    ):
                        try:
                            os.startfile(msg[1])
                        except Exception:
                            pass
                elif kind == "forensics_failed":
                    messagebox.showerror("生成失败", str(msg[1]))
                elif kind == "deep_audit":
                    self._sync_deep_button()
                    self._flash_status(
                        "深度归因已开启：正在记录进程创建，用于定位驱动安装的发起者"
                        if msg[1] else "深度归因已关闭，审计策略已恢复"
                    )
        except Exception:
            pass
        self.root.after(150, self._pump)

    def _tick(self):
        try:
            self._refresh()
        except Exception as exc:
            self._flash_status("刷新失败: %r" % (exc,))
        self.root.after(1200, self._tick)

    def _status_tick(self):
        try:
            stats = self.store.stats()
            state = "提醒已暂停" if self.app.paused else "监控中"
            last = stats["last_ts"]
            if last:
                delta = max(0, int(datetime.datetime.now().timestamp() - last))
                ago = "%s 秒前" % delta if delta < 60 else "%s 分钟前" % (delta // 60)
            else:
                ago = "暂无"
            admin = "管理员" if winapi.is_admin() else "普通权限"
            deep = ""
            audit = getattr(self.app, "audit", None)
            if audit is not None and audit.active:
                deep = " · 深度归因开"
            self.var_status.set(
                "%s · 今日 %d 条 · 累计 %d 条 · 最近事件 %s · %s%s"
                % (state, stats["today"], stats["total"], ago, admin, deep)
            )
        except Exception:
            pass
        self.root.after(2000, self._status_tick)

    # -- data --------------------------------------------------------------
    def _since(self):
        choice = self.var_range.get()
        now = datetime.datetime.now()
        if choice == "今天":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start.timestamp()
        if choice == "近 7 天":
            return (now - datetime.timedelta(days=7)).timestamp()
        if choice == "近 30 天":
            return (now - datetime.timedelta(days=30)).timestamp()
        return 0.0

    def _kind_value(self):
        text = self.var_kind.get()
        for name, value in KIND_CHOICES:
            if name == text:
                return value
        return ""

    def _is_filtered(self):
        return bool(
            self.var_search.get().strip()
            or self._kind_value()
            or self.var_problem.get()
        )

    def _load_initial(self):
        self._last_id = 0
        self._full_refresh()

    def _refresh(self):
        if self._is_filtered():
            self._full_refresh()
            return
        rows = self.store.after(self._last_id, 400) if self._last_id else self.store.query(
            since=0, limit=800, ascending=False
        )
        if not rows:
            return
        selected = self.tree.selection()
        for row in rows:
            self.tree.insert("", 0, iid=str(row["id"]), values=self._values(row),
                             tags=self._tags(row))
        self._last_id = max(self._last_id, max(int(r["id"]) for r in rows))
        if selected:
            for iid in selected:
                if self.tree.exists(iid):
                    self.tree.selection_set(iid)
                    break
        self.var_count.set("共 %d 条" % len(self.tree.get_children()))

    def _full_refresh(self):
        rows = self.store.query(
            text=self.var_search.get().strip(),
            kind=self._kind_value(),
            since=self._since(),
            only_problem=bool(self.var_problem.get()),
            limit=1500,
            ascending=False,
        )
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", iid=str(row["id"]), values=self._values(row),
                             tags=self._tags(row))
        if rows:
            self._last_id = max(self._last_id, max(int(r["id"]) for r in rows))
        if selected:
            for iid in selected:
                if self.tree.exists(iid):
                    self.tree.selection_set(iid)
                    break
        self.var_count.set("显示 %d 条" % len(rows))

    def _values(self, row):
        if row.get("vid") and row.get("pid"):
            ids = "VID %s / PID %s" % (row["vid"], row["pid"])
        else:
            instance = row.get("instance_id") or ""
            ids = instance.split("\\")[-1][:26] if instance else ""
        driver = row.get("driver") or ""
        version = row.get("driver_version") or ""
        if version:
            driver = (driver + " " + version).strip()
        note = row.get("note") or ""
        if int(row.get("merged_count") or 1) > 1:
            note = ("合并×%d " % int(row["merged_count"])) + note
        return (
            row.get("ts_text", ""),
            classify.label(row.get("kind", "")),
            row.get("name") or row.get("instance_id") or "",
            ids,
            driver,
            _clue_brief(row.get("clues")),
            note,
        )

    def _tags(self, row):
        kind = row.get("kind")
        if kind == "marker":
            return ("marker",)
        if kind == "alert":
            return ("alert",)
        severity = int(row.get("severity") or 0)
        if severity >= 3:
            return ("sev3",)
        if severity >= 2:
            return ("sev2",)
        return ()

    def _on_select(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        event_id = int(selected[0])
        row = self.store.get(event_id)
        if not row:
            return
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        clues = []
        try:
            clues = json.loads(row.get("clues") or "[]")
        except ValueError:
            clues = []
        detail = {}
        try:
            detail = json.loads(row.get("detail") or "{}")
        except ValueError:
            detail = {}
        lines = [
            "时间: " + row.get("ts_text", ""),
            "类型: %s (%s)" % (classify.label(row.get("kind", "")), row.get("kind")),
            "设备: " + (row.get("name") or ""),
            "实例: " + (row.get("instance_id") or ""),
            "类别: " + (row.get("class_name") or "—"),
        ]
        if row.get("vid"):
            lines.append("VID/PID: %s / %s   序列: %s" % (row.get("vid"), row.get("pid"), row.get("serial") or "—"))
        lines.append("驱动: %s %s" % (row.get("driver") or "—", row.get("driver_version") or ""))
        if int(row.get("merged_count") or 1) > 1:
            lines.append("合并: %d 条同源事件" % int(row["merged_count"]))
        if row.get("note"):
            lines.append("备注: " + row["note"])
        if clues:
            lines.append("")
            lines.append("触发线索:")
            for clue in clues:
                if isinstance(clue, dict):
                    lines.append(
                        "  · [%s] %s" % (clue.get("confidence", "?"), clue.get("text", ""))
                    )
        if detail:
            lines.append("")
            lines.append("原始详情:")
            text = json.dumps(detail, ensure_ascii=False, indent=1)
            lines.append(text[:5000])
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")

    # -- filters -----------------------------------------------------------
    def _schedule_search(self):
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(350, self._filter_changed)

    def _filter_changed(self):
        self._search_job = None
        self._full_refresh()

    # -- actions -----------------------------------------------------------
    def _apply_pause(self, paused):
        self.btn_pause.configure(text="恢复提醒" if paused else "暂停提醒")
        self._flash_status("已暂停弹窗提醒，事件仍会记录" if paused else "已恢复弹窗提醒")

    def _flash_status(self, text):
        self.var_status.set(text)

    def _deep_label(self):
        audit = getattr(self.app, "audit", None)
        return "深度归因：开" if audit is not None and audit.active else "深度归因：关"

    def _sync_deep_button(self):
        try:
            self.btn_deep.configure(text=self._deep_label())
        except Exception:
            pass

    def toggle_deep_audit(self):
        audit = getattr(self.app, "audit", None)
        if audit is None:
            return
        if not winapi.is_admin():
            messagebox.showinfo(
                "需要管理员权限",
                "深度归因会临时开启 Windows 的“进程创建”审计。\n\n"
                "请关闭本程序，双击 start_hwwatch_admin.bat 以管理员身份启动后再试。",
            )
            return
        enabling = not audit.active
        if enabling and not messagebox.askyesno(
            "开启深度归因",
            "将临时开启 Windows 的“进程创建”审计（包含命令行参数，可能含敏感信息），"
            "用于定位是哪个程序触发了驱动安装。\n\n"
            "退出程序时会自动恢复原有审计策略。是否继续？",
        ):
            return
        try:
            self.app.set_deep_audit(enabling)
        except Exception as exc:
            messagebox.showerror("操作失败", str(exc))
        self._sync_deep_button()

    def add_note(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先在列表中选择一条记录。")
            return
        note = simpledialog.askstring("添加备注", "给这条记录加个备注（例如：就是我听到的那声响）:")
        if not note:
            return
        self.store.add_note(int(selected[0]), note)
        self._full_refresh()
        self._on_select()

    def open_data_dir(self):
        try:
            os.startfile(str(config.data_dir()))
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            initialdir=str(config.export_dir()),
            initialfile="hwwatch_%s.csv" % datetime.datetime.now().strftime("%Y%m%d_%H%M"),
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            title="导出 CSV",
        )
        if not path:
            return
        rows = self.store.export_rows(since=self._since())
        try:
            exporter.export_csv(rows, path)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self._offer_open(path, len(rows))

    def export_html(self):
        path = filedialog.asksaveasfilename(
            initialdir=str(config.export_dir()),
            initialfile="hwwatch_%s.html" % datetime.datetime.now().strftime("%Y%m%d_%H%M"),
            defaultextension=".html",
            filetypes=[("HTML 报告", "*.html")],
            title="导出 HTML 时间线报告",
        )
        if not path:
            return
        rows = self.store.export_rows(since=self._since())
        try:
            exporter.export_html(rows, path, admin=winapi.is_admin())
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self._offer_open(path, len(rows))

    def _offer_open(self, path, count):
        if messagebox.askyesno("导出完成", "已导出 %d 条记录：\n%s\n\n现在打开吗？" % (count, path)):
            try:
                os.startfile(path)
            except Exception:
                pass

    # -- window ------------------------------------------------------------
    def hide_to_tray(self):
        self.root.withdraw()
        self._shown = False
        try:
            self.app.msg.set_tip("HwWatch 正在后台监控 · 双击托盘图标打开")
            self.app.msg.notify("HwWatch 仍在监控", "窗口已隐藏到托盘，事件会继续记录。")
        except Exception:
            pass

    def show(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass
        try:
            self.root.attributes("-topmost", True)
            self.root.after(600, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass
        self._shown = True

    def quit(self):
        try:
            self.app.stop()
        finally:
            self.root.destroy()
