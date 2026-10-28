# 验证与调试记录

本次测试日期：2026-10-28；Linux 5.15、GCC 11，原 GateANN 固定提交及课程 AIO 补丁。

1. 首次编译提示 `cblas.h` 不存在。原因是本机 OpenBLAS 以本地 deb 解压提供，系统
   默认头文件路径不含其目录。沿用基础实验 `CPLUS_INCLUDE_PATH` 后编译通过。
2. `build.py` 从原 `search_disk_index_yfcc` 的 compile_commands/link.txt 读取编译
   宏和链接配置，避免 AIO/AVX 宏与库 ABI 不一致；原算法源文件未新增改动。
3. C++ 边界测试全部通过：CSR 倒排、重复标签去重、零值项忽略、首尾与未知标签、
   选择率严格小于阈值、阈值为零时关闭枚举、空 Base、截断元数据拒绝。
4. Debug Low 前 5 条查询，将 M 设为足够大以精确重排全部匹配候选，Recall@10
   均为 100%。每个输出 ID 同时检查范围、标签约束和唯一性。
5. 新批次原图搜索 Recall 与旧基线一致：Low L=320 为 34.30%、L=1280 为
   70.05%，Medium L=320 为 72.05%，High L=320 为 93.25%。
6. 三轮 Medium/High 的原图与自适应回退、三轮 Low 原图与阈值为零的回退，
   合计 9 组结果 ID 文件逐字节相同，详见 `results/formal/fallback_checks.json`。
7. 39 次正式运行均正常退出，13 组配置各 3 次；`results/formal/summary.csv`
   只汇总该批结果，未混入预实验或 10 月 10 日基础实验。单次 CSV 各 200 行。
8. 原始实验日志、参数、输入/源码哈希与输出 ID 均保留。Ground Truth 在整批查询
   完成后才被打开评估，没有参与路由、PQ 预选或精确重排。

新增代码的持久化文件仅为实验结果与日志，不生成修改过的 SSD/PQ 基础索引。
倒排表内存容量、重建时间和整个进程峰值 RSS 分别报告；所有程序打印或 CSV 中的
逻辑 I/O 均不是独立块设备追踪结果。
