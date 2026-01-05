代码层面的具体建议
1. storage.py 的安全性
目前的 _get_file_path 虽然做了简单清理，但在生产环境中，直接用文件名拼接路径仍有风险。

建议：改用 SQLite 数据库存储方案。JSON 文件随着历史记录增多会变得难以管理，且无法进行复杂的查询（如：查询“张老师过去一年的所有课表”）。

2. 优化 Solver 性能
在 normal.py 中：

# 目前的写法
solver.parameters.max_time_in_seconds = 20
如果班级数量增加到 20+，20秒可能不够，或者结果不够好。

建议：

启用多线程求解：solver.parameters.num_search_workers = 8

分阶段求解：先满足硬约束（不超时），再在剩下的时间内优化软约束（减少连堂、黄金时间优化）。

3. 前端代码解耦
index.html 中的 JS 代码量已经很大了。

建议：将 JS 拆分为 api.js (负责 fetch), ui.js (负责 DOM 操作), drag_drop.js (负责交互)。这对于后续维护非常重要。