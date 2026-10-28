# computer-system：SSD 过滤向量检索与自适应优化

本仓库保存计算机系统课程实验的优化设计实现、测试脚本、实测结果和 Word 实验报告。
仓库地址：<https://github.com/Yi-Xiiiiiiii/computer-system>。

主要入口：[优化实现](src/adaptive_search.h)、[实验驱动](src/benchmark.cpp)、
[Word 实验报告](report/5-实验报告_含优化实现.docx)、[测试与调试记录](TESTING.md)。

课程基础实验来源：
<https://gitee.com/wei-fangyu/fvs-course-lab>。原 GateANN 固定版本为
`71e87cbf0e25c0400c0109dd25a64a7c4dccc9dd`。新增优化复用其 PQ、SSD 图记录和
Linux AIO 库，在独立 C++ 驱动中增加候选生成路径，没有修改原 GateANN 搜索实现。

## 目录

- `src/adaptive_search.h`：标签倒排表、选择率路由、分批 PQ 预选和 AIO 精确重排。
- `src/benchmark.cpp`：统一基线/优化驱动、逐查询计时、标签合法性检查和 Recall 评估。
- `scripts/`：构建、三轮对照实验、统计绘图及报告更新工具。
- `tests/`：CSR 与路由边界测试、Debug 全候选精确搜索验证。
- `results/formal/`：本次 39 次运行的逐查询 CSV、结果 ID、命令、资源记录与日志。
- `results/pilot/`：单轮预实验，不混入正式统计。
- `baseline/`：课程原始适配器、运行/下载脚本、参数和补丁副本，注明来源。
- `results/baseline_original/`：原基础实验的汇总及对应原始记录。
- `report/`：按五号宋体、1.25 倍行距更新的报告。

报告更新时保留了用户原稿 `report/source/5-实验报告_用户原稿.docx`；应使用
`report/5-实验报告_含优化实现.docx`。Word 目录为自动目录域，首次打开后可
更新目录以匹配本机分页，缓存目录没有沿用旧报告的失效页码。

## 优化逻辑

从完整 Base 标签元数据构建所有标签的 CSR 倒排表，全部保存在 DRAM。
每条查询用真实匹配数量 / Base 总数估计选择率。若选择率严格小于阈值 1%，
枚举匹配 ID，使用原索引的 PQ 距离保留前 M 个，以每批 8 个 AIO 请求读取原 SSD
索引中的完整向量并按精确 L2 距离返回 top-10；其余查询调用原 `pipe_search`。
默认代表配置为 M=40。Ground Truth 只在查询结束后用于评估，不参与候选生成。

当前实现范围为课程静态 uint8/L2、单标签过滤、单查询线程、identity ID/tag/page
映射。遇到非 identity 索引或不支持的查询格式会显式报错。未实现在线更新和多标签
交集路由。没有把数据集向量常驻 DRAM，也没有预缓存查询答案。

## 复现

先克隆本仓库并进入目录：

```bash
git clone https://github.com/Yi-Xiiiiiiii/computer-system.git
cd computer-system
```

需 Linux、GCC 11 或兼容版本、CMake、libaio、tcmalloc、OpenBLAS、Eigen3、Python3。
用于统计/报告的 Python 包见 `requirements.txt`。先按课程说明准备 GateANN、
Debug/Formal 数据与正式预构建索引。大数据、第三方源码及编译产物不包含在本目录。

如需从本目录准备基础实验，可把 `baseline/` 当作课程根目录，参照该目录 README
执行下载/构建/校验；以下命令中的 COURSE_ROOT 指向该根目录或已有课程仓库。

```bash
COURSE_ROOT=/absolute/path/to/fvs-course-lab
python3 scripts/build.py --gateann "$COURSE_ROOT/systems/GateANN-public"
python3 scripts/build.py --gateann "$COURSE_ROOT/systems/GateANN-public" --tests
python3 tests/check_correctness.py --course-root "$COURSE_ROOT"
python3 scripts/run_experiments.py --course-root "$COURSE_ROOT" \
  --out results/reproduced --repeats 3
python3 scripts/analyze.py --results results/reproduced
```

构建脚本从已构建的官方目标读取 ABI 宏、编译和链接参数，因此需要先完成课程
`prepare_gateann.sh`。本地解压依赖的用户应与基础实验相同设置 `CPLUS_INCLUDE_PATH`，
例如添加 OpenBLAS 头文件目录。运行脚本会识别课程本地 OpenBLAS 库目录；常规系统
安装时使用系统库。避免并行运行本实验与其他高负载任务。

每个输出目录必须是新路径，已有结果不覆盖。三轮运行交替反转配置顺序，查询阶段
不读 Ground Truth，不含元数据加载与倒排构建。初始化成本、整个进程峰值 RSS 单独记录。
`mean_latency_us` 为逐查询直接计时平均值；QPS 由整批 Query Phase 计算。逻辑 I/O
是提交的页面读取次数，不代表实际物理 SSD 读次数，未对相同页的多个请求去重。

## 实测取舍

三轮中位数，Low 200 条查询，同批重新测量的原 GateANN 基线：

| 配置 | Recall@10 | 平均延迟 ms | 逻辑 I/O/查询 |
|---|---:|---:|---:|
| 原 GateANN L=320 | 34.30% | 1.080 | 4.38 |
| 原 GateANN L=1280 | 70.05% | 3.202 | 13.945 |
| 自适应 M=10 | 72.75% | 0.553 | 10 |
| 自适应 M=20 | 91.40% | 0.740 | 20 |
| 自适应 M=40 | 98.35% | 1.083 | 40 |
| 自适应 M=80 | 99.75% | 1.920 | 80 |
| 自适应 M=160 | 100.00% | 3.698 | 160 |

新增倒排表有效分配容量为 44,934,300 字节，约 42.85 MiB；每次进程启动重建约
0.28 秒，不写额外持久化索引。峰值 RSS 由约 407 MiB 增至约 449 MiB。强过滤下
通过改善候选覆盖、避免不匹配节点穿越获益，并非所有配置都减少 I/O。
Medium/High 回退原路径，结果 ID 在三轮中与基线逐字节相同。
新测量与原始实验日期、驱动和计时口径不同，分别报告，不能拼成同一组重复实验。
参数在同一课程工作负载上选择，因此这些结果不是独立测试集上的泛化结论。

## GitHub 链接与报告

报告第 5.12 节使用本仓库的真实链接，并列出代码、实验记录及复现入口。
如需重新生成报告，可在仓库根目录安装 `requirements.txt` 中的依赖后执行：

```bash
python3 scripts/update_report.py \
  --source report/source/5-实验报告_用户原稿.docx \
  --output report/5-实验报告_含优化实现.docx \
  --github-url https://github.com/Yi-Xiiiiiiii/computer-system
```

`.gitignore` 排除构建产物和数据。建议同时保留本地大数据、原始日志和基础实验资料以供复核。

课程要求独立完成及独立撰写。提交前应自行理解、核查代码与报告，并按课程对辅助
工具的规定处理使用说明。该目录保留课程代码与第三方来源标注，不将上游代码标为新增实现。
