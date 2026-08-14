# Python版AI Agent Project
> 需要自己在系统环境变量中添加DeepSeek的OpenAI密钥，可以根据自身需求更换模型

## 启动方式
运行前置文件夹内的对应系统的文件来部署本地环境

1.双击启动器打开（主流）（有用户反馈说exe启动器会出现“0x0000142应用程序无法启动”的问题，由于目前样本太少，已知信息不多，求各位测试）

2.双击start.bat来启动command.py（备用和Debug用途）

## 下载包
> 本程序使用uv包管理器建立虚拟环境运行
python包目录存于母文件夹下requirement.txt

## 运行须知
> WindowsSettingBeta2是我制作的全自动环境配置脚本的第二个Beta版本，可能会出现不可描述的问题
ps:若发现本地无python包体会自动下载python13.5
请前往https://github.com/fiddeck/AI-Agent/issues 提交你发现的issue

## 目前问题&展望
> 1 set_event_loop_policy函数嵌套在asyncio上，本意是修复Windows上的异步事件循环问题，但是本函数已经被python14废弃，所以正在学习docker环境来避免这个问题

```python
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```
目前已经换回Python3.13.15，通过了本地实机测试

> 2 受到上下文字数限制有部分问题

> 3 老问题，docker环境什么时候上？
我不到哇，而且docker目前有点玩不来，在准备自用workbuddy的docker全自动可视化skill工具
