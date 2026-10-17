import pytest

from factorio_opc.game import GameError, parse_browse, parse_hello, parse_reply, parse_snapshot


def test_parse_reply_errors():
    with pytest.raises(GameError, match="not JSON"):
        parse_reply('Unknown command "opc_hello". Type /h for help.\n')
    with pytest.raises(GameError, match="unknown tag"):
        parse_reply('{"ok":false,"error":"unknown tag \'x\'"}')
    with pytest.raises(GameError, match="unexpected"):
        parse_reply("[1,2]")


def test_parse_hello():
    hello = parse_hello(parse_reply(
        '{"proto":1,"mod_version":"0.2.0","factorio_version":"2.0.77","tick":5,"tick_paused":false,'
        '"speed":1,"model_version":3,"ok":true}\n'))
    assert hello.tick == 5 and hello.speed == 1.0 and hello.model_version == 3


def test_parse_browse_accepts_empty_object_for_empty_list():
    assert parse_browse(parse_reply('{"tick":1,"model_version":0,"tags":{},"ok":true}')) == []
    tags = parse_browse(parse_reply(
        '{"ok":true,"tags":[{"name":"r","kind":"reader","unit":7,"surface":"nauvis","position":{"x":1.5,"y":2.5}}]}'))
    assert tags[0].name == "r" and tags[0].position == (1.5, 2.5)


def test_parse_snapshot_with_empty_tables():
    snap = parse_snapshot(parse_reply(
        '{"tick":9,"model_version":2,"readers":{"r":{"red":{"item/iron-plate":5},"green":{}}},'
        '"writers":{"w":{}},"ok":true}'))
    assert snap.readers["r"].red == {"item/iron-plate": 5}
    assert snap.readers["r"].green == {}
    assert snap.writers == {"w": {}}
    empty = parse_snapshot(parse_reply('{"tick":1,"model_version":0,"readers":{},"writers":{},"ok":true}'))
    assert empty.readers == {} and empty.writers == {}


def test_parse_snapshot_rejects_wrong_shapes():
    with pytest.raises(GameError):
        parse_snapshot({"tick": 1, "model_version": 0, "readers": [1], "writers": {}, "ok": True})


def test_parse_poll_delta_with_empty_tables():
    from factorio_opc.game import parse_poll

    poll = parse_poll(parse_reply(
        '{"seq":4,"full":false,"tick":10,"tick_paused":false,"speed":1,"model_version":2,'
        '"readers":{"r":{"red":{"item/iron-plate":0},"green":{}}},"writers":{},"removed":{},"ok":true}'))
    assert poll.seq == 4 and poll.full is False
    assert poll.readers["r"].red == {"item/iron-plate": 0} and poll.readers["r"].green == {}
    assert poll.writers == {} and poll.removed == []
