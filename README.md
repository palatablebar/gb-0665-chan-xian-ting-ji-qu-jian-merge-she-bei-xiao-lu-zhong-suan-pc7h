# 产线停机裁决与效率重算

班次按休息与停机所有端点切片，先扣休息并集，再按安全、故障、换型优先级分配停机。OEE使用未舍入的三因子计算，并保留超产异常。

使用者按采信、规则复算、异常复核和归档顺序处理一批数据。启动后自动装入异常样例，切换基准样例可比较两者结论。

## 启动与测试
```sh
docker compose up --build -d
docker compose exec -T app pytest -q
docker compose config --quiet
```

浏览器打开 [工作台](http://localhost:18204)。

## 业务模块

- 班报采信：导入班报并保留物理行号，入口 `/intake` 与 `GET /api/intake`。
- 班次契约：规范数量、节拍与偏移时间，入口 `/contract` 与 `GET /api/contract`。
- 停机裁决：裁剪并合并重叠区间，入口 `/model` 与 `GET /api/model`。
- 效率重算：复算三项效率及OEE，入口 `/calculate` 与 `GET /api/calculate`。
- 缺陷隔离：按原因筛查异常班报，入口 `/quarantine` 与 `GET /api/quarantine`。
- 班次对账：核查时间与产量守恒，入口 `/reconcile` 与 `GET /api/reconcile`。
- 运行复核：保存运行与版本复核，入口 `/batches` 与 `GET /api/batches`。

## 演示
选择样例后运行，核对业务结论与来源行。异常行保留原值和原因码。CSV证据只保留一个归档入口。

## 修订与生效
早班报复核后补发的修订值**不就地覆盖**现用结果，而是先登记为**待生效**版本：

- 同一组班次（产线+班次日期）的首次提交立即现用；之后的同组提交成为待生效版本，现用结果与原始依据均只读保留。
- 新修订到来时，上一个待生效版本转为已撤回；同一内容重复提交复用原运行记录，不新增重复版本。
- 工作台顶部始终标出本页版本状态（现用/待生效/已替换/已撤回），并给出当前采用版本及其运行号；`/batches` 的版本谱系、修订差异和原始记录页签给出逐字段与合计对比。
- 切换需待生效版本复核通过，并经 `POST /api/runs/{run_id}/adopt` 显式执行。切换是单事务条件更新：现用版本已变化返回 409 且整体回滚，旧现用保持不变；重复提交同一目标按已达成返回，不新增版本。
- 若修订缺失现用已覆盖的班次，切换返回 409 `COVERAGE` 并保留旧现用，避免丢记录。

## API
- `POST /api/runs`：JSON 中可指定 `sample`、`text` 与 `params`。
- `POST /api/runs/{run_id}/review`：提交 `revision`、`decision`。
- `POST /api/runs/{run_id}/adopt`：提交 `adopted_run_id`（期望的现用版本）与 `revision`，原子切换待生效版本。
- `GET /api/runs/{run_id}/evidence.csv`：来源证据。
- `GET /docs`：接口定义。

## 数据保存
SQLite 位于命名卷 records。相同内容、参数与规则版本只产生一条运行记录，重启不会产生新版本；旧库启动时自动迁移为版本谱系，原有修订号与审核状态保留。仅需重启时执行 `docker compose restart app`。要重新初始化样例数据，先备份所需记录，再执行 `docker compose down -v` 与 `docker compose up --build -d`；此操作会删除当前项目的历史与复核数据。

## 定义与边界
计划分钟=运行分钟+有效停机分钟。班次总分钟=计划分钟+休息并集分钟。总产=良品+废品。起止时间使用含偏移的ISO格式，班次最长24小时。区间采用[start,end)，超出班次的停机裁剪，重叠休息只扣一次。total与good为整数件，ideal_seconds为每件理想秒数。零计划、零运行、零产量分别给出状态，不以任意分母补零。

## 已知不覆盖
不推断缺失班报，不接入PLC。样例按班次隔离计算，不自动分割换产品后的节拍；混产品需分别生成班报。修订按班次组整批切换，不做逐条班次的部分生效；切换后未覆盖的旧记录仅保留在已替换版本中供追溯。

## 目录
`app/modules/` 为七个业务模块，`sample_data/` 提供基准与异常台账，`tests/` 包含模块测试与端到端测试，`docs/` 保存定义与深度登记。
