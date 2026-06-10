import asyncio
import sys
import types

import pytest

import bridge


class FakeNode:
    def __init__(self, nodeid, value):
        self.nodeid = nodeid
        self.value = value
        self.reads = 0

    async def read_value(self):
        self.reads += 1
        return self.value


def _cache_item(topic, node):
    return (topic, (node, "", "standard", "Float", topic.rsplit("/", 1)[-1], None))


@pytest.mark.asyncio
async def test_bounded_read_fallback_reads_cached_nodes(monkeypatch):
    monkeypatch.setattr(bridge, "OPC_READ_BATCH_SIZE", 2)
    poller = bridge.AsyncOpcPoller.__new__(bridge.AsyncOpcPoller)
    poller._batch_read_supported = False

    nodes = [FakeNode(f"ns=2;i={i}", i) for i in range(5)]
    items = [_cache_item(f"e/site/tag{i}", node) for i, node in enumerate(nodes)]

    values = await poller._read_cached_values(items, asyncio.Event())

    assert values == [0, 1, 2, 3, 4]
    assert [node.reads for node in nodes] == [1, 1, 1, 1, 1]


@pytest.mark.asyncio
async def test_batch_read_uses_opc_read_service(monkeypatch):
    monkeypatch.setattr(bridge, "OPC_READ_BATCH_SIZE", 2)

    class Variant:
        def __init__(self, value):
            self.Value = value

    class DataValue:
        def __init__(self, value):
            self.Value = Variant(value)
            self.StatusCode = None

    class FakeUaClient:
        def __init__(self):
            self.batch_sizes = []

        async def read(self, params):
            self.batch_sizes.append(len(params.NodesToRead))
            return [DataValue(read_id.NodeId) for read_id in params.NodesToRead]

    class FakeReadParameters:
        pass

    class FakeReadValueId:
        pass

    fake_ua = types.SimpleNamespace(
        ReadParameters=FakeReadParameters,
        ReadValueId=FakeReadValueId,
        TimestampsToReturn=types.SimpleNamespace(Neither="neither"),
        AttributeIds=types.SimpleNamespace(Value=13),
    )
    fake_asyncua = types.SimpleNamespace(ua=fake_ua)
    monkeypatch.setitem(sys.modules, "asyncua", fake_asyncua)

    poller = bridge.AsyncOpcPoller.__new__(bridge.AsyncOpcPoller)
    poller._opc = types.SimpleNamespace(uaclient=FakeUaClient())
    poller._batch_read_supported = True

    nodes = [FakeNode(f"node-{i}", i) for i in range(5)]
    items = [_cache_item(f"e/site/tag{i}", node) for i, node in enumerate(nodes)]

    values = await poller._read_cached_values(items, asyncio.Event())

    assert values == ["node-0", "node-1", "node-2", "node-3", "node-4"]
    assert poller._opc.uaclient.batch_sizes == [2, 2, 1]


@pytest.mark.asyncio
async def test_publish_batched_stops_between_chunks(monkeypatch):
    monkeypatch.setattr(bridge, "PUBLISH_BATCH_SIZE", 2)
    stop_event = asyncio.Event()
    published = []

    async def publish_one(topic, payload):
        published.append((topic, payload))
        if len(published) == 2:
            stop_event.set()

    count = await bridge._publish_batched(
        [("a", "1"), ("b", "2"), ("c", "3")],
        publish_one,
        stop_event,
    )

    assert count == 2
    assert published == [("a", "1"), ("b", "2")]


@pytest.mark.asyncio
async def test_browsepath_translation_splits_failed_chunks(monkeypatch):
    monkeypatch.setattr(bridge, "OPC_BROWSE_BATCH_SIZE", 4)

    class FakeUaClient:
        def __init__(self):
            self.batch_sizes = []

        async def translate_browsepaths_to_nodeids(self, browse_paths):
            self.batch_sizes.append(len(browse_paths))
            if len(browse_paths) > 2:
                raise RuntimeError("too many browse paths")
            return [f"node:{path}" for path in browse_paths]

    poller = bridge.AsyncOpcPoller.__new__(bridge.AsyncOpcPoller)
    poller._opc = types.SimpleNamespace(uaclient=FakeUaClient())

    values = await poller._translate_browsepaths_adaptive(["a", "b", "c", "d", "e"])

    assert values == ["node:a", "node:b", "node:c", "node:d", "node:e"]
    assert poller._opc.uaclient.batch_sizes == [4, 2, 2, 1]
