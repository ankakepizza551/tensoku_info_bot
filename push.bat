@echo off
echo =======================================
echo  Git Push Automation Script (tensoku)
echo =======================================
echo.

echo [+] ステージングエリアへファイルを登録中 (git add .)...
git add .
if %errorlevel% neq 0 (
    echo [ERROR] git add に失敗しました。Gitリポジトリが初期化されているか確認してください。
    goto end
)

echo.
set /p commit_msg="[INPUT] コミットメッセージを入力してください (未入力の場合: 「Add recruit and Elo features」): "

if "%commit_msg%"=="" (
    set commit_msg=Add recruit and Elo features
)

echo.
echo [+] コミット中 (git commit)...
git commit -m "%commit_msg%"
if %errorlevel% neq 0 (
    echo [WARN] コミットする変更がないか、コミットに失敗しました。
    goto end
)

echo.
echo [+] GitHubへ送信中 (git push)...
git push
if %errorlevel% neq 0 (
    echo [ERROR] git push に失敗しました。リモートリポジトリの設定や認証、ネットワーク接続を確認してください。
    goto end
)

echo.
echo [SUCCESS] GitHubへのプッシュが正常に完了しました！

:end
echo.
echo ボタンを押すと終了します...
pause > nul
