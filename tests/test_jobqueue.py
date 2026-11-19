import asyncio

from bot.jobqueue import FairQueue


def test_queue_order_and_positions():
    async def run():
        q = FairQueue(lambda: 1)
        seen = {}
        order = []

        def cb(name):
            async def f(n):
                seen.setdefault(name, []).append(n)
            return f

        async def work(name, delay):
            async with q.slot(cb(name)):
                order.append(name)
                await asyncio.sleep(delay)

        await asyncio.gather(work("a", 0.05), work("b", 0.01), work("c", 0.01))
        return order, seen

    order, seen = asyncio.run(run())
    assert order == ["a", "b", "c"]
    assert "a" not in seen                 # no esperó: no se le avisa
    assert seen["b"][0] == 1 and seen["b"][-1] == 0
    assert seen["c"][0] == 2 and 1 in seen["c"] and seen["c"][-1] == 0


def test_queue_parallel_limit_and_cancel():
    async def run():
        q = FairQueue(lambda: 2)
        running, peak = 0, 0

        async def work():
            nonlocal running, peak
            async with q.slot():
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.02)
                running -= 1

        tasks = [asyncio.create_task(work()) for _ in range(5)]
        await asyncio.sleep(0.005)
        tasks[4].cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return peak, q.active, len(q.waiting)

    peak, active, waiting = asyncio.run(run())
    assert peak == 2 and active == 0 and waiting == 0
