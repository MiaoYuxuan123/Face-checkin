# 人脸签到系统

三人团队课程项目。服务器端采用 Python + FastAPI，手机端采用原生 HTML/CSS/JavaScript，华为云 FRS 负责云端人脸检测、录入和一对多搜索，SQLite 保存用户及签到记录。

## 目录

```text
backend/       API、SQLite、FRS SDK 接入
frontend/      手机网页
tests/         不调用真实云服务的端到端接口测试
docs/          设计文档
data/private/   本地数据库与临时照片（自动创建，不进入 Git）
```

## 本地启动（PowerShell）

```powershell
cd D:\Codes\26autumn\CloudComputation\face-checkin
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:HUAWEICLOUD_SDK_AK = "你的 AK"
$env:HUAWEICLOUD_SDK_SK = "你的 SK"
$env:FRS_REGION = "cn-north-4"
$env:FRS_FACE_SET = "class_checkin"
.\.venv\Scripts\python.exe -m backend.setup_frs
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

`backend.setup_frs` 只需对新的人脸库执行一次。如果该人脸库已存在，跳过此命令。浏览器打开 `http://127.0.0.1:8000`。在注册页面填写信息并上传单人照片；注册成功后可以登录、注销。签到页面无需登录，已登记照片应返回成功或已签到，未登记照片应返回未找到人员。登记照会临时写到 `data/private/` 供 SDK 上传，调用结束即删除；数据库保留 FRS 人脸 ID，不保存原图。

需要在手机上测试时，服务器必须能被手机访问；公网部署时配置 HTTPS 和 `$env:COOKIE_SECURE = "1"`。直接用 `--host 0.0.0.0` 仅用于受控局域网开发，公网应放在 Nginx 后面并配置安全组。

## 管理员与数据库演示

注册一个测试账号后，在服务器上将其设为管理员：

```powershell
.\.venv\Scripts\python.exe -m backend.make_admin 用户名
```

管理员重新打开或刷新“登录与记录”页，可查看已登记人员和全部签到记录。普通用户只能查看自己的记录。要截取数据库变化，可在注册、签到前后执行以下只读命令：

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/private/checkin.sqlite3'); print('users=', c.execute('select count(*) from users').fetchone()[0]); print('checkins=', c.execute('select count(*) from checkins').fetchone()[0])"
```

## 当前范围与下一步

目前已接通前后端、注册录照、登录/注销、公开签到、个人及管理员记录查询。真实 FRS 调用需要有效 AK/SK、已开通 FRS 服务及人脸库。下一阶段加入活动管理、管理员照片维护、异步队列与限流，并在 ECS 上完成 HTTPS 部署。设计见 [第一次设计文档](docs/人脸签到系统-第一次设计文档.md)。

请勿提交 AK/SK、真实人脸照片、上传文件或本地数据库。
