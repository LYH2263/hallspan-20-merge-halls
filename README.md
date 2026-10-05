# HallSpan 考场间距排座

在考室网格上按最小曼哈顿距离排座，同试卷套不得四邻相邻，并输出违规与统计。

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
2. 打开「排座图」执行间距排座。
3. 在「违规」查看间距或同卷相邻问题。
4. 在「统计」查看占用与违规汇总。

## 两考室合排

- `POST /api/seating/merge?hall_a=1&hall_b=2`：两考室申请一次合排。成功则两室各落一条带同一 `merge_id` 的可对账方案；任一步失败则双室方案、统计、未排整体退回合排前，不留合排指针，未参与的第三室不被改动。
- `GET /api/seating/merge/{merge_id}`：合排对账，校验两室人数加总等于合排已座（`balanced`）。
- 合排后 `GET /api/seating/latest?hall_id=` / `stats?hall_id=` 分室查看，两室人数相加等于合排已座。

## 开发与测试

```bash
docker compose exec api pytest -q
```
