# -*- coding: utf-8 -*-
"""后台任务调度。

设计要点：
    - **三通道三线程**：``fast``（读取目录子项，极快）、``scan``（目录大小扫描，耗时）、
      ``batch``（空间估算 / 清理）各由一个工作线程消费，互不阻塞；
    - **优先级队列**：同一通道内按 ``priority`` 调度（数值越小越先执行），
      用户主动触发的清理可优先于排队中的估算任务；
    - 每个通道维护独立的世代号 (generation)，``reset`` 后旧任务与其结果会被自动丢弃，
      用于「刷新 / 重新估算」时取消过期工作；
    - 任务函数签名 ``fn(gen, ev)``，``ev`` 是可用于协作式取消的 ``threading.Event``；
    - 任务通过 ``emit`` 把结果投递回主线程，由注册的 handler 在主线程处理。
"""

import queue
import threading

# 承载任务的工作线程（lane）
LANE_FAST = "fast"        # 读取目录子项
LANE_SCAN = "scan"        # 目录大小扫描
LANE_BATCH = "batch"      # 空间估算 / 清理
LANES = (LANE_FAST, LANE_SCAN, LANE_BATCH)

# 优先级建议
PRIORITY_URGENT = 0    # 停止信号 / 紧急
PRIORITY_LIST = 1      # 读取目录子项（很快，必须最先返回）
PRIORITY_CLEAN = 2     # 用户主动点击的清理
PRIORITY_SCAN = 3      # 目录大小扫描（耗时）
PRIORITY_BATCH = 5     # 空间估算等批量任务

# 停止信号：priority 最小，会排在最前面被立即取出
_STOP = (-1, -1, None)


class TaskRunner:
    """两条工作线程 + 优先级队列 + 世代号的任务调度器。"""

    def __init__(self, root, poll_ms=120):
        self.root = root
        self.poll_ms = poll_ms
        self.error_sink = None  # callable(str)，用于上报 handler 异常

        self._channels = {}     # name -> [generation, Event]
        self._handlers = {}     # name -> callable(kind, payload)
        self._lanes = {}        # name -> lane
        self._queues = {lane: queue.PriorityQueue() for lane in LANES}
        self._results = queue.Queue()
        self._after_id = None
        self._seq = 0
        self._seq_lock = threading.Lock()

        self._threads = []
        for lane in LANES:
            t = threading.Thread(target=self._worker, args=(self._queues[lane],),
                                 daemon=True)
            t.start()
            self._threads.append(t)

        self._schedule_poll()

    # ---------------- 注册 / 提交 ----------------

    def register(self, name, handler, lane=LANE_BATCH):
        """注册通道及其结果处理器。handler(kind, payload)。"""
        self._channels.setdefault(name, [0, threading.Event()])
        self._handlers[name] = handler
        self._lanes[name] = lane

    def _next_seq(self):
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def submit(self, name, fn, priority=PRIORITY_BATCH, lane=None):
        """提交任务到指定通道。fn(gen, ev)。

        priority 越小越先执行；lane 可覆盖通道默认的工作线程。
        """
        if name not in self._channels:
            raise KeyError("未注册的通道: %s" % name)
        lane = lane or self._lanes.get(name, LANE_BATCH)
        gen, ev = self._channels[name]
        self._queues[lane].put((priority, self._next_seq(), (name, gen, ev, fn)))

    def emit(self, name, gen, kind, payload):
        """任务函数内部调用：把结果投递回主线程。"""
        self._results.put((name, gen, kind, payload))

    def reset(self, name):
        """使通道内所有在跑/待跑任务过期（协作式取消）。"""
        gen, ev = self._channels[name]
        ev.set()
        self._channels[name] = [gen + 1, threading.Event()]

    def current_gen(self, name):
        return self._channels[name][0]

    # ---------------- 工作线程 ----------------

    def _worker(self, q):
        while True:
            priority, _seq, payload = q.get()
            if payload is None:  # 停止信号
                return
            name, gen, ev, fn = payload
            if self._channels.get(name, [None])[0] != gen:
                continue  # 已过期，丢弃
            try:
                fn(gen, ev)
            except Exception as e:  # noqa: BLE001
                self.emit(name, gen, "log", "后台任务出错：%s" % e)

    # ---------------- 主线程轮询 ----------------

    def _schedule_poll(self):
        self._after_id = self.root.after(self.poll_ms, self._poll)

    def _poll(self):
        try:
            while True:
                name, gen, kind, payload = self._results.get_nowait()
                if self._channels.get(name, [None])[0] != gen:
                    continue
                handler = self._handlers.get(name)
                if handler is None:
                    continue
                try:
                    handler(kind, payload)
                except Exception as e:  # noqa: BLE001
                    if self.error_sink:
                        self.error_sink("结果处理失败(%s/%s)：%s" % (name, kind, e))
        except queue.Empty:
            pass
        self._schedule_poll()

    # ---------------- 关闭 ----------------

    def stop(self):
        try:
            if self._after_id is not None:
                self.root.after_cancel(self._after_id)
        except Exception:  # noqa: BLE001
            pass
        self._after_id = None
        for name in list(self._channels):
            self._channels[name][1].set()
        for lane in LANES:
            self._queues[lane].put(_STOP)
