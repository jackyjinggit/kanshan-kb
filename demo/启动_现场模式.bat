@echo off
rem Kanshan live-demo launcher (local mode: visitor signs in with their own Zhihu account on this PC)
rem First run: fill in the three values below (or set them as system env vars and delete this block)
if "%ZHIHU_OAUTH_APP_ID%"=="" set ZHIHU_OAUTH_APP_ID=paste_AppID_here
if "%ZHIHU_OAUTH_APP_KEY%"=="" set ZHIHU_OAUTH_APP_KEY=paste_AppKey_here
if "%ZHIHU_ACCESS_SECRET%"=="" set ZHIHU_ACCESS_SECRET=paste_AccessSecret_here
if "%OAUTH_REDIRECT_URI%"=="" set OAUTH_REDIRECT_URI=http://127.0.0.1:8699/oauth/callback
echo [1/2] Gateway starting at http://127.0.0.1:8699/  (v2 timeline UI; classic engine at /classic)
cd /d %~dp0..
start "" /min pythonw demo\heartbeat.py
python demo\server.py --port 8699
