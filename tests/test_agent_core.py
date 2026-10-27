"""agent_core 单元测试: 设置、会话存储、上下文裁剪、Agent 循环。"""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

import agent_core as core

# --------------------------------------------------------------------------- #
# 设置
# --------------------------------------------------------------------------- #

def test_settings_accept_legacy_pascal_case(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "Model": "legacy-model",
        "BaseUrl": "https://example.com/v1/",
        "ApiKey": "sk-legacy",
        "Port": 8123,
        "FontSize": 17,
        "Accent": "#ff8800",
        "Background": "#ffffff",
    }), encoding="utf-8")

    settings = core.Settings.load(path)

    assert settings.model == "legacy-model"
    assert settings.base_url == "https://example.com/v1"
    assert settings.api_key == "sk-legacy"
    assert settings.port == 8123
    assert settings.font_size == 17
    assert settings.accent == "#FF8800"
    assert settings.background == "#FFFFFF"
    assert settings.api_key_source == "file"


def test_settings_validation_and_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "model": "   ",
        "port": 99999,
        "fontSize": 99,
        "accent": "红色",
        "background": "#12345",
    }), encoding="utf-8")

    settings = core.Settings.load(path, use_env=False)

    assert settings.model == core.DEFAULT_MODEL
    assert settings.port == 65535
    assert settings.font_size == 26
    assert settings.accent == core.DEFAULT_ACCENT
    assert settings.background == core.DEFAULT_BACKGROUND


def test_broken_settings_file_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert core.Settings.load(path, use_env=False).model == core.DEFAULT_MODEL


def test_env_key_has_priority_but_is_not_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"apiKey": ""}), encoding="utf-8")

    settings = core.Settings.load(path)
    assert settings.api_key == "sk-from-env"
    assert settings.api_key_source == "env"

    settings.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["apiKey"] == "", "环境变量里的密钥不应被写进 settings.json"


def test_settings_manager_merges_and_writes_camel_case(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"Model": "old", "custom": "keep-me"}), encoding="utf-8")

    manager = core.SettingsManager(path)
    settings = manager.update({"model": "new-model", "api_key": "sk-file", "accent": "#00ff00"})

    assert settings.model == "new-model"
    assert settings.api_key == "sk-file"
    assert settings.api_key_source == "file"

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["model"] == "new-model"
    assert saved["apiKey"] == "sk-file"
    assert saved["accent"] == "#00FF00"
    assert saved["custom"] == "keep-me", "未知字段应保留"

    # 空密钥不覆盖已有值，除非显式 clear_api_key
    manager.update({"api_key": ""})
    assert manager.current().api_key == "sk-file"
    manager.update({"clear_api_key": True})
    assert manager.current().api_key == ""


def test_settings_manager_reloads_on_external_change(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "one"}), encoding="utf-8")
    manager = core.SettingsManager(path)
    assert manager.current().model == "one"

    import time
    time.sleep(0.01)
    path.write_text(json.dumps({"model": "two"}), encoding="utf-8")

    assert manager.current().model == "two"


# --------------------------------------------------------------------------- #
# 会话存储
# --------------------------------------------------------------------------- #

def test_session_store_roundtrip(tmp_path):
    store = core.SessionStore(tmp_path / "sessions")
    session = store.create(title="测试会话")
    sid = session["sid"]

    session["messages"] = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你？"},
        {"role": "tool", "content": "不应保存"},
    ]
    store.save(session)

    loaded = store.load(sid)
    assert loaded is not None
    assert loaded["title"] == "测试会话"
    assert [m["role"] for m in loaded["messages"]] == ["user", "assistant"]

    listed = store.list()
    assert len(listed) == 1
    assert listed[0]["sid"] == sid
    assert listed[0]["message_count"] == 2
    assert store.latest()["sid"] == sid

    assert store.delete(sid) is True
    assert store.load(sid) is None
    assert store.list() == []


def test_session_store_rejects_invalid_sid(tmp_path):
    store = core.SessionStore(tmp_path)
    assert store.load("../../etc/passwd") is None
    assert store.delete("a/b") is False
    with pytest.raises(ValueError):
        store.save({"sid": "../evil", "messages": []})


def test_session_store_ignores_corrupt_files(tmp_path):
    store = core.SessionStore(tmp_path)
    (tmp_path / "broken.json").write_text("{oops", encoding="utf-8")
    store.create(title="ok")
    assert len(store.list()) == 1


def test_session_store_prune(tmp_path):
    store = core.SessionStore(tmp_path)
    for index in range(5):
        session = store.create(title=f"s{index}")
        session["updated_at"] = f"2026-01-0{index + 1}T00:00:00+08:00"
        store.save(session)
    assert store.prune(keep=2) == 3
    assert len(store.list()) == 2


# --------------------------------------------------------------------------- #
# 工具格式 / 参数解析 / 提示词
# --------------------------------------------------------------------------- #

def test_to_openai_tools_handles_object_and_mapping():
    class Tool:
        name = "read_file"
        description = "读取文件"
        inputSchema = {"type": "object", "properties": {"path": {"type": "string"}}}

    converted = core.to_openai_tools([Tool(), {"name": "list_files", "description": "列举"}])
    assert [item["function"]["name"] for item in converted] == ["read_file", "list_files"]
    assert converted[0]["function"]["parameters"]["properties"]["path"]["type"] == "string"
    assert converted[1]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_parse_tool_args():
    assert core.parse_tool_args('{"a": 1}') == ({"a": 1}, None)
    assert core.parse_tool_args("") == ({}, None)
    args, error = core.parse_tool_args("{bad")
    assert args == {} and error
    args, error = core.parse_tool_args("[1, 2]")
    assert args == {} and "对象" in error


def test_build_system_prompt_contains_tools_and_env():
    prompt = core.build_system_prompt(["read_file", "run_shell_command"])
    assert "read_file" in prompt and "run_shell_command" in prompt
    assert "安全边界" in prompt
    assert "Windows" in prompt or "操作系统" in prompt


def test_make_title():
    assert core.make_title("  你好\n世界\t! ") == "你好 世界 !"
    assert core.make_title("", ) == "新对话"
    assert len(core.make_title("x" * 100)) == 25


# --------------------------------------------------------------------------- #
# 上下文裁剪
# --------------------------------------------------------------------------- #

def test_trim_messages_keeps_system_and_recent_rounds():
    messages = [{"role": "system", "content": "sys"}]
    for index in range(4):
        messages.append({"role": "user", "content": "u" * 100})
        messages.append({"role": "assistant", "content": "a" * 100})

    trimmed = core.trim_messages(messages, max_chars=450)

    assert trimmed[0]["role"] == "system"
    assert trimmed[1]["role"] == "user"
    assert core.count_message_chars(trimmed) <= 450
    assert len(trimmed) < len(messages)


def test_trim_messages_never_leaves_orphan_tool_message():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u" * 100},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "t" * 100},
        {"role": "user", "content": "u" * 100},
    ]
    trimmed = core.trim_messages(messages, max_chars=120)
    assert trimmed[0]["role"] == "system"
    assert trimmed[1]["role"] == "user"
    assert all(not (m["role"] == "tool") for m in trimmed[:2])


def test_trim_messages_noop_when_under_limit():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert core.trim_messages(messages, max_chars=1000) == messages


# --------------------------------------------------------------------------- #
# 输出解码
# --------------------------------------------------------------------------- #

def test_decode_process_output_handles_gbk_and_utf8():
    assert core.decode_process_output("中文测试".encode("gbk")) == "中文测试"
    assert core.decode_process_output("中文测试".encode("utf-8")) == "中文测试"
    assert core.decode_process_output(b"\xff\xfe\x00")  # 不抛异常


def test_decode_process_output_tolerates_truncated_utf8():
    text = "中文测试" * 10
    raw = text.encode("utf-8")[:-1]  # 末尾只剩半个汉字
    decoded = core.decode_process_output(raw)
    assert decoded.startswith("中文测试" * 9)
    assert decoded.count("\ufffd") <= 1


# --------------------------------------------------------------------------- #
# AgentRunner
# --------------------------------------------------------------------------- #

def _chunk(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tool_delta(index=0, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class _Stream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for chunk in self._chunks:
            yield chunk


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        # 深拷贝: runner 会继续修改 messages 列表，快照才能反映"当时"发给模型的请求
        self.requests.append(copy.deepcopy(kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Stream(item)


def _fake_client(responses):
    return SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(responses)))


def _collect(runner, messages):
    async def scenario():
        return [event async for event in runner.run(messages)]

    return asyncio.run(scenario())


def test_runner_streams_text_and_finishes():
    client = _fake_client([[_chunk("你"), _chunk("好")]])
    runner = core.AgentRunner(client, "mock", [], lambda name, args: None)
    messages = [{"role": "user", "content": "hi"}]

    events = _collect(runner, messages)

    assert "".join(e["content"] for e in events if e["type"] == "token") == "你好"
    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["content"] == "你好"
    assert runner.final_text == "你好"
    assert messages[-1] == {"role": "assistant", "content": "你好"}


def test_runner_executes_tool_and_continues():
    calls: list[tuple[str, dict]] = []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        return "文件列表: a.txt"

    client = _fake_client([
        [
            _chunk(tool_calls=[_tool_delta(0, "call_1", "list_files", '{"pa')]),
            _chunk(tool_calls=[_tool_delta(0, None, None, 'th": "."}')]),
        ],
        [_chunk("完成")],
    ])
    runner = core.AgentRunner(client, "mock", [{"type": "function"}], call_tool)
    messages = [{"role": "user", "content": "列目录"}]

    events = _collect(runner, messages)

    assert calls == [("list_files", {"path": "."})]
    tool_call = [e for e in events if e["type"] == "tool_call"][0]
    assert tool_call["name"] == "list_files"
    tool_result = [e for e in events if e["type"] == "tool_result"][0]
    assert "a.txt" in tool_result["content"]

    second_request = client.chat.completions.requests[1]
    assert second_request["messages"][-1]["role"] == "tool"
    assert second_request["messages"][-1]["content"].startswith("文件列表")
    assert second_request["messages"][-2]["tool_calls"][0]["function"]["name"] == "list_files"
    assert runner.final_text == "完成"


def test_runner_handles_invalid_tool_arguments():
    async def call_tool(name, arguments):  # pragma: no cover - 不应被调用
        raise AssertionError("参数非法时不应执行工具")

    client = _fake_client([
        [_chunk(tool_calls=[_tool_delta(0, "c1", "read_file", "{not json")])],
        [_chunk("好的")],
    ])
    runner = core.AgentRunner(client, "mock", [], call_tool)
    events = _collect(runner, [{"role": "user", "content": "x"}])

    result = [e for e in events if e["type"] == "tool_result"][0]
    assert "未执行" in result["content"]


def test_runner_stops_at_max_steps():
    async def call_tool(name, arguments):
        return "ok"

    responses = [[_chunk(tool_calls=[_tool_delta(0, f"c{i}", "get_datetime", "{}")])]
                 for i in range(3)]
    runner = core.AgentRunner(_fake_client(responses), "mock", [], call_tool, max_steps=2)
    events = _collect(runner, [{"role": "user", "content": "loop"}])

    errors = [e for e in events if e["type"] == "error"]
    done = [e for e in events if e["type"] == "done"]
    assert errors and "最大工具调用次数" in errors[0]["message"]
    assert done and done[0]["truncated"] is True


def test_runner_retries_transient_error(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(core.asyncio, "sleep", fake_sleep)
    client = _fake_client([
        RuntimeError("network glitch"),
        [_chunk("ok")],
    ])
    runner = core.AgentRunner(client, "mock", [], lambda n, a: None, retries=1)
    events = _collect(runner, [{"role": "user", "content": "hi"}])

    assert runner.final_text == "ok"
    assert sleeps == [1.2]
    assert not [e for e in events if e["type"] == "error"]


def test_runner_reports_api_error():
    class ApiError(Exception):
        status_code = 401

    runner = core.AgentRunner(_fake_client([ApiError("unauthorized")]), "mock", [],
                               lambda n, a: None, retries=0)
    events = _collect(runner, [{"role": "user", "content": "hi"}])

    errors = [e for e in events if e["type"] == "error"]
    assert errors and "API Key" in errors[0]["message"]
