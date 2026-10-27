using System;
using System.Collections.Generic;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AIAgentGUI;

/// <summary>
/// 与本地 webui.py 后端通信的 WebSocket 客户端。
/// 协议与 webui.py 的 /ws 端点一一对应，未知消息类型会被忽略(便于后端向前兼容)。
/// </summary>
public sealed class ChatService
{
    private ClientWebSocket? _ws;
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private int _generation;   // 重连代数: 旧接收循环结束时不应误报 Disconnected

    // 服务端 -> 客户端事件 (均在接收线程触发, 使用方需自行调度到 UI 线程)
    public event Action<int, string>? Ready;                       // 工具数量 + 模型名
    public event Action<string>? SessionChanged;                    // 新会话 sid
    public event Action<List<SessionInfo>>? SessionsUpdated;        // 会话列表
    public event Action<string, List<HistoryMessage>>? HistoryReceived; // sid + 历史
    public event Action<string>? UserMessageReceived;               // 用户消息(服务端回显)
    public event Action<string>? TokenReceived;                     // 流式文本增量
    public event Action<string, string>? ToolCallReceived;          // 工具名 + 参数(JSON串)
    public event Action<string, string>? ToolResultReceived;        // 工具名 + 结果文本
    public event Action<bool>? TurnDone;                            // 本轮结束 (是否被用户停止)
    public event Action<string>? ErrorReceived;
    public event Action? Disconnected;

    public async Task ConnectAsync(string uri)
    {
        var generation = ++_generation;
        _ws?.Dispose();
        _ws = new ClientWebSocket();
        await _ws.ConnectAsync(new Uri(uri), CancellationToken.None);
        _ = ReceiveLoopAsync(_ws, generation);
    }

    public async Task SendNewChat() => await SendAsync("{\"type\":\"new_chat\"}");

    /// <summary>断开连接并释放 (设置变更重启后端后重连用)。</summary>
    public void Close()
    {
        _generation++;
        try { _ws?.Abort(); } catch { }
        try { _ws?.Dispose(); } catch { }
        _ws = null;
    }

    public async Task SendSwitch(string sid) =>
        await SendAsync($"{{\"type\":\"switch\",\"sid\":{JsonSerializer.Serialize(sid)}}}");

    public async Task SendChat(string sid, string content) =>
        await SendAsync($"{{\"type\":\"chat\",\"sid\":{JsonSerializer.Serialize(sid)},\"content\":{JsonSerializer.Serialize(content)}}}");

    /// <summary>请求停止当前会话的生成；若正在执行工具，后端会结束工具进程。</summary>
    public async Task SendStop(string? sid) =>
        await SendAsync($"{{\"type\":\"stop\",\"sid\":{JsonSerializer.Serialize(sid ?? "")}}}");

    private async Task SendAsync(string json)
    {
        var socket = _ws;
        if (socket == null || socket.State != WebSocketState.Open) return;
        var bytes = Encoding.UTF8.GetBytes(json);
        await _sendLock.WaitAsync();
        try
        {
            await socket.SendAsync(new ArraySegment<byte>(bytes),
                WebSocketMessageType.Text, true, CancellationToken.None);
        }
        catch
        {
            // 连接已断开, 由接收循环统一上报
        }
        finally
        {
            _sendLock.Release();
        }
    }

    private async Task ReceiveLoopAsync(ClientWebSocket socket, int generation)
    {
        var buffer = new byte[64 * 1024];
        var accumulator = new MemoryStream();
        try
        {
            while (socket.State == WebSocketState.Open)
            {
                var result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), CancellationToken.None);
                if (result.MessageType == WebSocketMessageType.Close) break;
                if (result.MessageType != WebSocketMessageType.Text) continue;

                // 一条 WebSocket 消息可能被拆成多帧，必须累积到 EndOfMessage 再解析
                accumulator.Write(buffer, 0, result.Count);
                if (!result.EndOfMessage) continue;

                var json = Encoding.UTF8.GetString(accumulator.GetBuffer(), 0, (int)accumulator.Length);
                accumulator.SetLength(0);
                try { HandleMessage(json); }
                catch { /* 单条消息解析失败则跳过, 不影响后续 */ }
            }
        }
        catch
        {
            // 连接异常
        }
        accumulator.Dispose();
        if (generation == _generation)
            Disconnected?.Invoke();
    }

    private void HandleMessage(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (!root.TryGetProperty("type", out var typeProperty)) return;
        var type = typeProperty.GetString();

        switch (type)
        {
            case "ready":
                Ready?.Invoke(ReadInt(root, "tools"), ReadString(root, "model"));
                break;

            case "session":
                SessionChanged?.Invoke(ReadString(root, "sid"));
                EmitSessions(root, "sessions");
                break;

            case "sessions":
                EmitSessions(root, "list");
                break;

            case "history":
            {
                var sid = ReadString(root, "sid");
                var list = new List<HistoryMessage>();
                if (root.TryGetProperty("messages", out var messages) &&
                    messages.ValueKind == JsonValueKind.Array)
                {
                    foreach (var m in messages.EnumerateArray())
                    {
                        var role = ReadString(m, "role", "assistant");
                        var content = ReadString(m, "content");
                        list.Add(new HistoryMessage(role, content));
                    }
                }
                HistoryReceived?.Invoke(sid, list);
                break;
            }

            case "user_message":
                UserMessageReceived?.Invoke(ReadString(root, "content"));
                break;

            case "token":
                TokenReceived?.Invoke(ReadString(root, "content"));
                break;

            case "tool_call":
                ToolCallReceived?.Invoke(ReadString(root, "name", "?"), ReadString(root, "arguments"));
                break;

            case "tool_result":
                ToolResultReceived?.Invoke(ReadString(root, "name", "?"), ReadString(root, "content"));
                break;

            case "done":
                TurnDone?.Invoke(ReadBool(root, "stopped"));
                break;

            case "error":
                ErrorReceived?.Invoke(ReadString(root, "message", "未知错误"));
                break;
        }
    }

    private void EmitSessions(JsonElement root, string property)
    {
        var list = new List<SessionInfo>();
        if (root.TryGetProperty(property, out var array) && array.ValueKind == JsonValueKind.Array)
        {
            foreach (var s in array.EnumerateArray())
            {
                list.Add(new SessionInfo(ReadString(s, "sid"), ReadString(s, "title")));
            }
        }
        SessionsUpdated?.Invoke(list);
    }

    private static string ReadString(JsonElement element, string property, string fallback = "")
    {
        if (!element.TryGetProperty(property, out var value)) return fallback;
        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString() ?? fallback,
            JsonValueKind.Null or JsonValueKind.Undefined => fallback,
            _ => value.ToString(),
        };
    }

    private static int ReadInt(JsonElement element, string property, int fallback = 0)
    {
        if (!element.TryGetProperty(property, out var value)) return fallback;
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number) ? number : fallback;
    }

    private static bool ReadBool(JsonElement element, string property)
    {
        return element.TryGetProperty(property, out var value) &&
               value.ValueKind == JsonValueKind.True;
    }
}
