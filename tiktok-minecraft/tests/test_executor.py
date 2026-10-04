import asyncio

from tiktok_mc.executor import CommandQueue
from tiktok_mc.rcon import RconError


class FakeSender:
    def __init__(self, fail_times=0, reply=""):
        self.sent: list[str] = []
        self.fail_times = fail_times
        self.reply = reply

    async def command(self, text):
        if self.fail_times:
            self.fail_times -= 1
            raise RconError("down")
        self.sent.append(text)
        return self.reply

    async def close(self):
        pass


async def drain(queue: CommandQueue, timeout=3.0):
    task = asyncio.create_task(queue.run())
    for _ in range(int(timeout / 0.01)):
        if queue.pending == 0:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_runs_in_order_and_skips_wait():
    async def scenario():
        sender = FakeSender()
        queue = CommandQueue(sender, commands_per_second=1000)
        queue.submit("a", ["say 1", "wait 0.05", "say 2"])
        queue.submit("b", ["say 3"])
        await drain(queue)
        return sender.sent, queue.pending

    sent, pending = asyncio.run(scenario())
    assert sent == ["say 1", "say 2", "say 3"]
    assert pending == 0


def test_overflow_is_dropped():
    queue = CommandQueue(FakeSender(), max_queue=3)
    assert queue.submit("a", ["1", "2"])
    assert not queue.submit("b", ["3", "4"])
    assert queue.pending == 2
    assert queue.dropped_count == 2


def test_retries_until_server_is_back():
    async def scenario():
        sender = FakeSender(fail_times=2)
        queue = CommandQueue(sender, commands_per_second=1000, retry_delay=0.01)
        queue.submit("a", ["say hi"])
        await drain(queue)
        return sender.sent

    assert asyncio.run(scenario()) == ["say hi"]


def test_minecraft_error_reply_does_not_stop_queue():
    async def scenario():
        sender = FakeSender(reply="Unknown or incomplete command, see below for error")
        queue = CommandQueue(sender, commands_per_second=1000)
        queue.submit("a", ["sumon zombie", "sumon zombie"])
        await drain(queue)
        return sender.sent, queue._warned_errors

    sent, warned = asyncio.run(scenario())
    assert len(sent) == 2
    assert warned == {"a:sumon"}
