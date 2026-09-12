@echo off
rem 看山 · 现场演示一键启动（本机模式：评委用本机浏览器登录自己知乎号测试）
rem 首次使用：把活动页分配的三个值填进下面（或设为系统环境变量后删除本节）
if "%ZHIHU_OAUTH_APP_ID%"=="" set ZHIHU_OAUTH_APP_ID=填活动页AppID
if "%ZHIHU_OAUTH_APP_KEY%"=="" set ZHIHU_OAUTH_APP_KEY=填活动页AppKey
if "%ZHIHU_ACCESS_SECRET%"=="" set ZHIHU_ACCESS_SECRET=填开放平台AccessSecret
if "%OAUTH_REDIRECT_URI%"=="" set OAUTH_REDIRECT_URI=http://127.0.0.1:8699/oauth/callback
echo [1/2] 启动演示网关 http://127.0.0.1:8699/  （默认打开 v2 三屏页；引擎旧版在 /classic）
cd /d %~dp0..
start "" /min pythonw demo\heartbeat.py
python demo\server.py --port 8699
