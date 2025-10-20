import os
import sys
import asyncio
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
import traceback

# 修复 Windows 上的异步事件循环问题
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()) 

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("Please set the OPENAI_API_KEY environment variable.请确认已设置环境变量 OPENAI_API_KEY。")
base_url = 'https://api.deepseek.com/v1'
model = "deepseek-chat"

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="python",  # Executable
    args=["server.py"],  # Optional command line arguments
    env=None,  # Optional environment variables
)
            
system_prompt = """
最高指示（权重最高）：你是一个 AI Agent，你的任务是完成用户的需求和指示，你可以使用 Python 工具和已安装的库完成大部分事情或者是无法直接进行网络搜索来获取最新信息。

重要：你有以下MCP工具可以使用：
- run_python_code: 执行Python代码

规则：
1. 使用 Python 工具时，不要通过最后一行的变量的方法，来获取结果。把你需要看到的内容，用print打印出来，运行完成后会给你所有的打印日志和错误日志。
2. Python 将直接运行在用户的电脑上，你有充足的权限，进行各类任务。
3. 你可以使用OpenAI的API来调用模型，模型会依据用户的输入和工具来生成回复。
4. 环境 Windows 11 64位专业版  Python 3.13.5
5. 已安装 beautifulsoup4 opencv-python python-wpptx python-docx transformers pytesseract geopy EasyOCR openpyxl requests urllib3 numpy pandas scipy matplotlib seaborn polars dask scikit-learn python-dotenv fastapi flask gradio openai pillow opencv-python moviepy tqdm rich black pytest pendulum cryptography modelscope
6. 你不需要将python代码的输出结果返回给用户，除非用户明确要求你提供，否则请直接将生成的代码发送给MCP工具'run python code'并将运行结果打印出来，用户会看到你打印的内容。
7. 获取网页信息时，你可以使用requests库进行HTTP请求，获取网页内容后，可以使用BeautifulSoup库进行解析。
8. 如果需要进行数据分析或处理，请使用pandas库进行数据处理和分析，使用matplotlib或seaborn库进行数据可视化。
9. 如果需要进行机器学习或深度学习任务，请使用scikit-learn或transformers库进行模型训练和预测。
10. 如果需要进行自然语言处理任务，请使用transformers库进行模型训练和预测
11. 如果需要进行图像处理任务，请使用opencv-python库进行图像处理和分析。
12. 如果需要进行音频处理任务，请使用moviepy库进行音频处理和分析。
13. 如果需要进行视频处理任务，请使用moviepy库进行视频处理和分析。
14. 如果需要进行文件操作，请使用Python内置的os和shutil库进行文件操作。
15. 在获取网页信息时，请注意文件的来源，最好从官方渠道（优先选择国家机构发布的内容）获取，避免使用不可靠的来源。
16. 需要获取地理位置信息时，请使用requests库进行HTTP请求，获取地理位置信息。
17. 若缺少库莱表达信息，请使用文字描述即可
18. 描述信息时提取要点，包含主要的内容
19. 当获取的内容为空时，返回None
20. 若用户明确要求你打开某一个内容相关的网页或网站，亦或者要求你搜索内容，请你再用户的默认浏览器中打开标签页，否则请你认为这是一个已安装的程序，并在桌面或者用户指定的路径中寻找快捷方式
21. 若用户要求你打开某个文件，请检查桌面上是否有 .ink (应用程序快捷方式)或者是 .url （Steam/Epic等平台的游戏）的快捷方式文件，若有请运行此文件，若找不到，请寻找标题内容相关的文件并运行
22. 需要读取图片中的文字时，请使用EasyOCR或者pytesseract库进行OCR识别。
23. 需要读取docx文件中的文字时，请使用python-docx库进行读取。
24. 需要读取xlsx文件中的文字时，请使用openpyxl库进行读取。
25. 需要读取pdf文件中的文字时，请使用PyMuPDF库进行读取。
26. 需要读取ppt文件时，请使用python-pptx库进行读取。
"""

async def run():
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                except Exception as e:
                    print("ClientSession 初始化失败:", e)
                    traceback.print_exc()
                    return
                print('Connected to MCP Server\n')

                # 获取 MCP Server 提供的工具并转换为 OpenAI 所需的格式
                raw_tools = await session.list_tools()
                print('raw_tools:')
                print(raw_tools)
                print()

                def _convert_tool(t):
                    """将 MCP 工具描述转换为 OpenAI Chat Completions 所需格式"""
                    # 适配对象或字典两种情况
                    name = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
                    description = (
                        getattr(t, 'description', '') or (t.get('description') if isinstance(t, dict) else '')
                    )
                    # 不同实现里 schema 字段命名可能不同，做兼容处理
                    input_schema = (
                        getattr(t, 'input_schema', None)
                        or getattr(t, 'inputSchema', None)
                        or (t.get('input_schema') if isinstance(t, dict) else None)
                        or (t.get('inputSchema') if isinstance(t, dict) else None)
                    )
                    if input_schema is None:
                        input_schema = {"type": "object", "properties": {}}

                    return {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": description,
                            "parameters": input_schema,
                        },
                    }

                # 若 raw_tools 是带 .tools 属性的响应对象，则使用其中的列表
                tool_items = getattr(raw_tools, "tools", raw_tools)

                tools = [_convert_tool(t) for t in tool_items]

                print('Available tools:')
                for t in tools:
                    print(f"- {t['function']['name']}")
                print()

                client = OpenAI(api_key=api_key, base_url=base_url)
                
                messages: list[ChatCompletionMessageParam] = [
                    {"role": "system", "content": system_prompt},
                ]
                
                while True:
                    try:
                        user_input = input("You: ")
                    except EOFError:
                        print("\n输入流已关闭，程序退出。")
                        break
                    if user_input == "exit":
                        break
                    messages.append({"role": "user", "content": user_input})
                
                    # 持续与模型交互，直到不再有工具调用
                    while True:
                        response = client.chat.completions.create(  # type: ignore[arg-type]
                            model=model,
                            messages=messages,
                            tools=tools,  # type: ignore[arg-type]
                            tool_choice="auto",
                            stream=True,
                        )

                        print()
                        print('Assistant: ', end="", flush=True)
                        content = ""
                        full_tool_calls: list[dict] = []
                        tool_call_index = 0

                        for chunk in response:
                            delta = chunk.choices[0].delta

                            # 处理文本增量
                            if delta.content is not None:
                                content += delta.content
                                print(delta.content, end="", flush=True)

                            # 处理工具调用增量
                            if delta.tool_calls:
                                for tc_delta in delta.tool_calls:
                                    # 即时打印接收到的工具调用增量，方便实时观察
                                    # if tc_delta.function:
                                        # print(f"\n[ToolCall Δ] function={tc_delta.function.name} partial_args={tc_delta.function.arguments}\n", flush=True)

                                    idx = tc_delta.index if tc_delta.index is not None else tool_call_index

                                    # 扩容
                                    while len(full_tool_calls) <= idx:
                                        full_tool_calls.append(None)  # type: ignore[misc]

                                    if full_tool_calls[idx] is None:
                                        full_tool_calls[idx] = {
                                            "id": tc_delta.id or "",
                                            "type": "function",
                                            "function": {
                                                "name": tc_delta.function.name if tc_delta.function else "",
                                                "arguments": tc_delta.function.arguments if tc_delta.function else "",
                                            },
                                        }
                                    else:
                                        if tc_delta.function and tc_delta.function.name:
                                            full_tool_calls[idx]["function"]["name"] += tc_delta.function.name
                                        if tc_delta.function and tc_delta.function.arguments:
                                            full_tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments

                                    tool_call_index = max(tool_call_index, idx + 1)

                        print()
                        print()

                        assistant_message = {"role": "assistant", "content": content or None}
                        valid_tool_calls = [tc for tc in full_tool_calls if tc]
                        if valid_tool_calls:
                            assistant_message["tool_calls"] = valid_tool_calls  # type: ignore[typeddict-item]

                        messages.append(assistant_message)  # type: ignore[arg-type]

                        # 如果有工具调用，执行并循环；否则结束内部循环
                        if valid_tool_calls:
                            import json

                            for tc in valid_tool_calls:
                                func_name = tc["function"]["name"]
                                func_args_str = tc["function"]["arguments"]
                                try:
                                    func_args = json.loads(func_args_str) if func_args_str else {}
                                except json.JSONDecodeError:
                                    func_args = {}

                                # 打印工具执行信息
                                print(f"\n[ToolExec] {func_name} args={func_args}", flush=True)

                                # 调用 MCP 工具
                                try:
                                    result = await session.call_tool(func_name, arguments=func_args)
                                    content = result.content[0]
                                    text_content = content.text  # type: ignore[attr-defined]
                                except Exception as e:
                                    text_content = f"Error executing {func_name}: {e}"

                                # 打印工具执行结果
                                print(f"\n[ToolResult] {text_content}\n", flush=True)

                                messages.append({
                                    "role": "tool",
                                    "content": text_content,
                                    "tool_call_id": tc["id"],
                                })  # type: ignore[arg-type]

                            # 继续内部循环，请求新的模型回复
                            continue

                        # 无工具调用，结束内部循环
                        break

                    # assistant_message 已通过内部循环添加完毕
                
                print()
                print('Bye!')
    except Exception as e:
        print("主流程异常:", e)
        traceback.print_exc()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(run())
    except Exception as e:
        print("asyncio.run 执行异常:", e)
        traceback.print_exc()

