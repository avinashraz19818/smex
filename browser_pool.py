import os
import sys
import json
import asyncio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER_SCRIPT = os.path.join(BASE_DIR, "browser_worker.py")


class BrowserWorker:
    def __init__(self, idx, phone, password, owner_id):
        self.idx = idx
        self.phone = phone
        self.password = password
        self.owner_id = owner_id
        self.proc = None
        self.reader_task = None
        self.ready = asyncio.Event()
        self.done = asyncio.Event()
        self.failed_reason = ""
        self.status = ""
        self.healthy = False
        self.collecting = False
        self.lines = []

    @property
    def alive(self):
        return self.proc is not None and self.proc.returncode is None

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, WORKER_SCRIPT, str(self.idx), self.phone, self.password, self.owner_id,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=BASE_DIR,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        self.reader_task = asyncio.create_task(self._read_output())

    async def _read_output(self):
        while True:
            raw = await self.proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")

            if line.startswith("__READY__"):
                self.status = line[len("__READY__"):]
                self.healthy = True
                self.ready.set()
                print(f"✅ Browser {self.idx} ready — {self.status}")
                continue
            if line.startswith("__READY_FAILED__"):
                self.failed_reason = line[len("__READY_FAILED__"):]
                self.status = self.failed_reason
                self.healthy = False
                self.ready.set()
                print(f"⚠️ Browser {self.idx} problem — {self.failed_reason}")
                continue
            if line.startswith("__BET_DONE__"):
                self.done.set()
                continue
            if line.startswith("__REFRESH_DONE__") or line.startswith("__KEEPALIVE_DONE__"):
                marker = "__REFRESH_DONE__" if line.startswith("__REFRESH_DONE__") else "__KEEPALIVE_DONE__"
                self.status = line[len(marker):]
                self.healthy = "ready" in self.status or "ok (" in self.status or "khola" in self.status
                self.done.set()
                continue

            if self.collecting:
                self.lines.append(line)
            print(f"[Client {self.idx}] {line}")

        print(f"⚠️ Browser {self.idx} process band ho gaya")
        self.ready.set()
        self.done.set()

    async def send(self, payload):
        if not self.alive:
            return False
        try:
            self.proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
            return True
        except Exception as e:
            print(f"⚠️ Browser {self.idx} ko command nahi bheji ja payi: {e}")
            return False

    async def stop(self):
        if not self.alive:
            return
        await self.send({"cmd": "shutdown"})
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=15)
        except asyncio.TimeoutError:
            try:
                self.proc.kill()
            except Exception:
                pass


class BrowserPool:
    def __init__(self, owner_id, accounts):
        self.owner_id = owner_id
        self.workers = [
            BrowserWorker(i + 1, acc.get("phone", ""), acc.get("password", ""), owner_id)
            for i, acc in enumerate(accounts)
        ]
        self.lock = asyncio.Lock()

    def ready_workers(self):
        return [w for w in self.workers if w.alive and w.ready.is_set()]

    def ready_count(self):
        return len(self.ready_workers())

    def healthy_workers(self):
        return [w for w in self.ready_workers() if w.healthy]

    def healthy_count(self):
        return len(self.healthy_workers())

    def problem_workers(self):
        return [w for w in self.workers if not w.healthy]

    async def start(self, timeout=None):
        if timeout is None:
            timeout = max(240, 30 * len(self.workers))

        print(f"🌐 {len(self.workers)} browsers khol raha hoon (owner {self.owner_id})...")
        for w in self.workers:
            await w.start()
            await asyncio.sleep(1.0)

        try:
            await asyncio.wait_for(
                asyncio.gather(*[w.ready.wait() for w in self.workers]),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            slow = [w.idx for w in self.workers if not w.ready.is_set()]
            print(f"⚠️ Browser {slow} time pe ready nahi hue — background me khulte rahenge")

        print(f"🌐 {self.healthy_count()}/{len(self.workers)} browsers WinGo board pe ready")
        bad = self.problem_workers()
        if bad:
            for w in bad:
                print(f"   ⚠️ Browser {w.idx}: {w.failed_reason or w.status or 'ready nahi hua'} "
                      f"— /refresh try karo")
        return self.healthy_count()

    async def _broadcast(self, payload, timeout, collect=False):
        async with self.lock:
            targets = self.ready_workers()
            if not targets:
                return [], ""

            for w in targets:
                w.done.clear()
                w.lines = []
                w.collecting = collect

            sent = []
            for w in targets:
                if await w.send(payload):
                    sent.append(w)

            if sent:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*[w.done.wait() for w in sent]),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    stuck = [w.idx for w in sent if not w.done.is_set()]
                    print(f"⚠️ Browser {stuck} ne {timeout}s me jawab nahi diya")

            output = ""
            for w in sent:
                w.collecting = False
                if collect:
                    output += "\n".join(w.lines) + "\n"
            return sent, output

    async def bet(self, mode="bet", period=None, timeout=300):
        payload = {"cmd": "bet", "mode": mode}
        if period:
            payload["period"] = period
        sent, output = await self._broadcast(payload, timeout=timeout, collect=True)
        return output

    async def refresh(self, timeout=180):
        sent, _ = await self._broadcast({"cmd": "refresh"}, timeout=timeout)
        return {w.idx: (w.status.strip() or "no status") for w in sent}

    async def keepalive(self, timeout=120):
        sent, _ = await self._broadcast({"cmd": "keepalive"}, timeout=timeout)
        return {w.idx: (w.status.strip() or "no status") for w in sent}

    async def stop(self):
        await asyncio.gather(*[w.stop() for w in self.workers], return_exceptions=True)
