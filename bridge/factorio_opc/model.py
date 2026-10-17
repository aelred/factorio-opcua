"""The bridge's OPC UA address space (see docs/address-space.md).

Objects/Factorio/
  Status/   Connected, GameTick, TickPaused, GameSpeed, ModVersion, FactorioVersion,
            ModelVersion, LastPollLatencyMs
  Readers/<tag>/  Red/<signal>, Green/<signal>, Total/<signal>  (Int32, read-only)
  Writers/<tag>/  Signals/<signal> (Int32, writable), SetSignals(), ClearAll()

NodeIds are strings in the factorio-opc namespace that spell out the path,
e.g. "Readers/line_1/Red/item/iron-plate", so clients can address them directly.
Signal nodes are created the first time a signal is seen and then kept (at 0)
for as long as their tag exists, so subscriptions stay valid. A signal seen on
either wire of a reader gets a node in Red, Green and Total.

Values are pushed straight into the address space instead of through a
session write, so only client writes reach the write interception in server.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from asyncua import Server, ua
from asyncua.common.node import Node

from .game import Hello, SignalMap, Snapshot, Tag

NAMESPACE_URI = "urn:factorio-opc"

GOOD = ua.StatusCode(ua.StatusCodes.Good)
STALE = ua.StatusCode(ua.StatusCodes.UncertainNoCommunicationLastUsableValue)

READER_CHANNELS = ("Red", "Green", "Total")

# (tag name, json signals, mode) -> new signals; raises ua.UaStatusCodeError on failure.
MethodHandler = Callable[[str, str, str], Awaitable[str]]


def wrap_int32(value: int) -> int:
    """Circuit arithmetic wraps around at 32 bits; red + green does the same in game."""
    return (value + 2**31) % 2**32 - 2**31


def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TagNodes:
    tag: Tag
    root: Node
    channels: dict[str, Node]                      # "Red"/"Green"/"Total" or "Signals" folder nodes
    signals: dict[tuple[str, str], Node] = field(default_factory=dict)  # (channel, key) -> variable
    values: dict[tuple[str, str], int] = field(default_factory=dict)    # last value pushed


class AddressSpace:
    def __init__(self, server: Server, ns: int) -> None:
        self._server = server
        self._aspace = server.iserver.aspace
        self.ns = ns
        self.tags: dict[str, TagNodes] = {}
        # Writer signal NodeId -> (tag name, signal key); used by the write interception.
        self.writer_signal_nodes: dict[ua.NodeId, tuple[str, str]] = {}
        self._status: dict[str, Node] = {}
        self._stale = False

    def nodeid(self, path: str) -> ua.NodeId:
        return ua.NodeId(path, self.ns)

    def qname(self, name: str) -> ua.QualifiedName:
        return ua.QualifiedName(name, self.ns)

    async def build(self) -> None:
        objects = self._server.nodes.objects
        root = await objects.add_object(self.nodeid("Factorio"), self.qname("Factorio"))
        status = await root.add_object(self.nodeid("Status"), self.qname("Status"))
        for name, value, vtype in (
            ("Connected", False, ua.VariantType.Boolean),
            ("GameTick", 0, ua.VariantType.UInt64),
            ("TickPaused", False, ua.VariantType.Boolean),
            ("GameSpeed", 0.0, ua.VariantType.Double),
            ("ModVersion", "", ua.VariantType.String),
            ("FactorioVersion", "", ua.VariantType.String),
            ("ModelVersion", 0, ua.VariantType.UInt32),
            ("LastPollLatencyMs", 0.0, ua.VariantType.Double),
        ):
            self._status[name] = await status.add_variable(
                self.nodeid(f"Status/{name}"), self.qname(name), value, vtype
            )
        self.readers = await root.add_folder(self.nodeid("Readers"), self.qname("Readers"))
        self.writers = await root.add_folder(self.nodeid("Writers"), self.qname("Writers"))

    async def _push(self, node: Node, variant: ua.Variant, status: ua.StatusCode = GOOD,
                    source_time: datetime | None = None) -> None:
        stamp = now()
        dv = ua.DataValue(Value=variant, StatusCode=status, SourceTimestamp=source_time or stamp,
                          ServerTimestamp=stamp)
        await self._aspace.write_attribute_value(node.nodeid, ua.AttributeIds.Value, dv)

    # -- status --------------------------------------------------------------

    async def set_connected(self, hello: Hello | None) -> None:
        await self._push(self._status["Connected"], ua.Variant(hello is not None, ua.VariantType.Boolean))
        if hello is not None:
            await self.set_status(hello)

    async def set_status(self, hello: Hello, latency_ms: float | None = None) -> None:
        for name, value, vtype in (
            ("GameTick", hello.tick, ua.VariantType.UInt64),
            ("TickPaused", hello.tick_paused, ua.VariantType.Boolean),
            ("GameSpeed", hello.speed, ua.VariantType.Double),
            ("ModVersion", hello.mod_version, ua.VariantType.String),
            ("FactorioVersion", hello.factorio_version, ua.VariantType.String),
            ("ModelVersion", hello.model_version, ua.VariantType.UInt32),
        ):
            await self._push(self._status[name], ua.Variant(value, vtype))
        if latency_ms is not None:
            await self._push(self._status["LastPollLatencyMs"], ua.Variant(latency_ms, ua.VariantType.Double))

    # -- tags ----------------------------------------------------------------

    async def sync_tags(self, tags: list[Tag], method_handler: MethodHandler) -> None:
        """Add nodes for new tags and delete nodes of tags that are gone.

        A renamed tag shows up as one removal and one addition.
        """
        wanted = {t.name: t for t in tags}
        for name in [n for n, nodes in self.tags.items() if n not in wanted or wanted[n].kind != nodes.tag.kind]:
            await self._remove_tag(name)
        for name, tag in wanted.items():
            if name not in self.tags:
                await self._add_tag(tag, method_handler)

    async def _remove_tag(self, name: str) -> None:
        nodes = self.tags.pop(name)
        for nodeid in [n for n, (tag, _) in self.writer_signal_nodes.items() if tag == name]:
            del self.writer_signal_nodes[nodeid]
        await self._server.delete_nodes([nodes.root], recursive=True)

    async def _add_tag(self, tag: Tag, method_handler: MethodHandler) -> None:
        if tag.kind == "reader":
            base = f"Readers/{tag.name}"
            root = await self.readers.add_object(self.nodeid(base), self.qname(tag.name))
            channels = {
                c: await root.add_folder(self.nodeid(f"{base}/{c}"), self.qname(c)) for c in READER_CHANNELS
            }
        else:
            base = f"Writers/{tag.name}"
            root = await self.writers.add_object(self.nodeid(base), self.qname(tag.name))
            channels = {"Signals": await root.add_folder(self.nodeid(f"{base}/Signals"), self.qname("Signals"))}
            await self._add_writer_methods(root, base, tag.name, method_handler)
        self.tags[tag.name] = TagNodes(tag=tag, root=root, channels=channels)

    async def _add_writer_methods(self, root: Node, base: str, name: str, handler: MethodHandler) -> None:
        # asyncua turns exceptions from methods into BadUnexpectedError; a returned
        # StatusCode is passed to the client as the call's result instead.
        async def set_signals(parent, *args: ua.Variant):
            # Mode may be left out (defaults to "merge"); simple CLI clients find that easier.
            if not args:
                return ua.StatusCode(ua.StatusCodes.BadArgumentsMissing)
            if len(args) > 2:
                return ua.StatusCode(ua.StatusCodes.BadTooManyArguments)
            values = [a.Value for a in args]
            if any(v is not None and not isinstance(v, str) for v in values):
                return ua.StatusCode(ua.StatusCodes.BadTypeMismatch)
            signals_json = values[0] or "{}"
            mode = (values[1] if len(values) > 1 else None) or "merge"
            try:
                result = await handler(name, signals_json, mode)
            except ua.UaStatusCodeError as exc:
                return ua.StatusCode(exc.code)
            return [ua.Variant(result, ua.VariantType.String)]

        async def clear_all(parent, *args: ua.Variant):
            if args:
                return ua.StatusCode(ua.StatusCodes.BadTooManyArguments)
            try:
                await handler(name, "{}", "replace")
            except ua.UaStatusCodeError as exc:
                return ua.StatusCode(exc.code)
            return []

        signals_arg = ua.Argument(Name="SignalsJson", DataType=ua.NodeId(ua.ObjectIds.String), ValueRank=-1,
                                  Description=ua.LocalizedText('JSON object, e.g. {"item/iron-plate": 5}; 0 removes'))
        mode_arg = ua.Argument(Name="Mode", DataType=ua.NodeId(ua.ObjectIds.String), ValueRank=-1,
                               Description=ua.LocalizedText('"merge" (default, may be omitted) or "replace"'))
        result_arg = ua.Argument(Name="Signals", DataType=ua.NodeId(ua.ObjectIds.String), ValueRank=-1,
                                 Description=ua.LocalizedText("The writer's full output after the call, as JSON"))
        await root.add_method(self.nodeid(f"{base}/SetSignals"), self.qname("SetSignals"), set_signals,
                              [signals_arg, mode_arg], [result_arg])
        await root.add_method(self.nodeid(f"{base}/ClearAll"), self.qname("ClearAll"), clear_all, [], [])

    async def _signal_node(self, nodes: TagNodes, channel: str, key: str) -> Node:
        node = nodes.signals.get((channel, key))
        if node is None:
            base = "Readers" if nodes.tag.kind == "reader" else "Writers"
            node = await nodes.channels[channel].add_variable(
                self.nodeid(f"{base}/{nodes.tag.name}/{channel}/{key}"), self.qname(key), 0, ua.VariantType.Int32
            )
            if nodes.tag.kind == "writer":
                await node.set_writable()
                self.writer_signal_nodes[node.nodeid] = (nodes.tag.name, key)
            nodes.signals[(channel, key)] = node
            nodes.values[(channel, key)] = 0
        return node

    async def _apply_channel(self, nodes: TagNodes, channel: str, values: SignalMap, when: datetime,
                             extra_keys: set[str] = frozenset()) -> None:
        keys = set(values) | set(extra_keys) | {k for (c, k) in nodes.signals if c == channel}
        for key in sorted(keys):
            value = values.get(key, 0)
            node = await self._signal_node(nodes, channel, key)
            if self._stale or nodes.values.get((channel, key)) != value:
                nodes.values[(channel, key)] = value
                await self._push(node, ua.Variant(value, ua.VariantType.Int32), GOOD, when)

    async def apply_writer(self, name: str, values: SignalMap, when: datetime | None = None) -> None:
        nodes = self.tags.get(name)
        if nodes is not None and nodes.tag.kind == "writer":
            await self._apply_channel(nodes, "Signals", values, when or now())

    async def apply_snapshot(self, snapshot: Snapshot, when: datetime) -> None:
        for name, nodes in self.tags.items():
            if nodes.tag.kind == "reader":
                r = snapshot.readers.get(name)
                if r is None:
                    continue
                total = dict(r.red)
                for k, v in r.green.items():
                    total[k] = wrap_int32(total.get(k, 0) + v)
                # A signal seen on either wire gets a node in all three channels.
                for channel, values in (("Red", r.red), ("Green", r.green), ("Total", total)):
                    await self._apply_channel(nodes, channel, values, when, extra_keys=set(total))
            elif name in snapshot.writers:
                await self._apply_channel(nodes, "Signals", snapshot.writers[name], when)
        self._stale = False

    async def mark_stale(self) -> None:
        """Flag every tag value as last-known (connection to the game lost)."""
        if self._stale:
            return
        self._stale = True
        await self.set_connected(None)
        for nodes in self.tags.values():
            for (channel, key), node in nodes.signals.items():
                value = nodes.values[(channel, key)]
                await self._push(node, ua.Variant(value, ua.VariantType.Int32), STALE)
