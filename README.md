# HallSpan 考场间距排座

在考室网格上按最小曼哈顿距离排座，同试卷套不得四邻相邻，并输出违规与统计。
支持两考室一次合排：成功则两室都留下可对账方案与统一指针、考生不丢、分室人数相加等于合排已座；
任一步失败则两室方案/统计/未排全部回滚、无残留指针；未参与的第三室不被改动。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4900 |
| API | http://localhost:9900 |
| API 文档 | http://localhost:9900/docs |
| Postgres | localhost:5450 |

健康检查：`GET http://localhost:9900/api/health`

## 使用说明

1. 在「考室」「考生」「试卷套」确认基础数据。
2. 在「考室」页选择两间独立考室，点击「申请合排」（或在「排座图」单室排座）。
3. 打开「排座图」执行间距排座，切换考室查看分室/合排方案。
4. 在「违规」查看间距或同卷相邻问题。
5. 在「统计」查看占用与违规汇总；合排时显示分室人数与合排合计（两者相等）。

## 合排事务保证

- `POST /api/seating/merge` 在**单事务**内写两室对账方案（共享 `merge_key`）并立统一指针
  （`halls.merged_into` 指向主室）；计算失败或提交异常均整体回滚。
- 数据库触发器（PostgreSQL/SQLite 双方言）强制：
  合排方案必须有座位、同批次至多两室、有指针必有本室与主室对账座位、批次一致、禁止指针改派。
- 分室视图（`/seating/latest|stats|violations`）跟随统一指针，返回本室切片与 `merged_stats`，
  两室 `seated` 之和恒等于合排已座。

## 开发与测试

```bash
docker compose exec api pytest -q
```
