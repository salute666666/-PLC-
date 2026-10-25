# Prompt library

Copy-paste these into a new conversation after the plugin is installed.

## Environment

```text
用 plc_environment 检查 PLC 插件环境，告诉我 Python、ISPSoft 路径和工作区。
```

## Read

```text
打开 D:\work\Demo.isp
列出所有 ST 程序、型号、POU 数量和任务；告诉我 test 在哪个任务。
```

```text
在刚才的工程里搜索 D555，告诉我它出现在哪些 POU、哪些行。
```

```text
把 HMI 程序的代码读出来，按功能分段解释，不要修改。
```

## Edit ST

```text
把 test 改成：D555 每周期加一，到 100 清零。先写代码并自检，再给我 diff。
```

```text
在 GearBox 里增加一个 3 秒超时报警：启动后 3 秒内没有反馈就置位 M100。
只改 GearBox，写完给我 diff。
```

## Ladder self-lock

```text
新建梯形图子程序 自锁：M0 启动、M1 停止、Y0.1 电机、M2 运行指示，挂到任务 1。
生成后告诉我它排在哪个 POU 后面。
```

```text
把自锁的启动点改成 X1.0、停止点改成 X1.1，重新生成一个叫 自锁2 的程序，挂任务 0。
```

## Export / open / compile

```text
导出工程并用 ISPSoft 打开，告诉我输出路径和文件大小。
```

```text
导出后我要在 ISPSoft 里编译。把编译步骤和要检查的点列给我。
```

## Review

```text
审查自锁程序：有没有双线圈、急停是否只依赖软件、停止按钮是常闭还是常开、扫描周期是否可控。
```

## Rollback

```text
回滚所有改动，恢复到打开工程时的状态。
```
