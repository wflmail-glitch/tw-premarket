# ROUTINE：台股盤前整理（每個交易日 08:07 台北時間）

你是排程啟動的雲端 session。照下列步驟做，全部在 repo 根目錄執行。時間一律用台北時間。

## 1. 抓證交所數據（程式算，不要自己算）
```
python3 scripts/fetch_market.py
```
- 印出「今天休市」→ `python3 scripts/build_report.py && python3 scripts/send.py`（只送一行「今天休市」），跳到第 6 步。
- 失敗（exit 2）→ `python3 scripts/build_report.py && python3 scripts/send.py` 送出失敗原因，跳到第 6 步。
- 個別資料缺（market.json 的 missing）→ 繼續，報告會自動標「無資料／今日缺少」。

## 2. 新聞候選
```
python3 scripts/news.py fetch
```

## 3. 挑 5~8 則、讀內文
從候選清單挑出對「今天開盤」最有用的 5~8 則：大盤／法人動向、美股與台指期夜盤、台積電等權值股重大消息、匯率、政策、觀察清單（config.toml）相關個股或 ETF。避免重複事件、避免純個人理財與網友心得文。
```
python3 scripts/news.py select <id> <id> ...
```
然後閱讀 `data/<今天>/news_selected.json` 的 body。

## 4. 寫 data/<今天>/ai.md（只寫這三段）
```
## 今日重點
（3~4 點。把數字和新聞連起來講「為什麼」。數字只能從 data/<今天>/market.json 照抄，不准用新聞數字、不准自己換算出新數字）
## 新聞
（5~8 則，每則一句摘要＋（來源）。數字只能照抄該則內文）
## 今天要注意
（今天或近日的財經行事曆，如法說會、除權息、重要數據公布；沒有就留空）
```
硬規定：**不推薦、不預測、不寫分析師看法與目標價**。新聞與證交所數字衝突時，以證交所為準並在該則註明。

## 5. 組報告 → 核對 → 送出
```
python3 scripts/build_report.py
python3 scripts/verify_report.py
```
- 核對失敗：依列出的數字修改 ai.md（刪掉或改成有出處的數字），重跑兩支，最多 3 輪。
- 通過後：`python3 scripts/send.py`

## 6. 存回 GitHub
```
git add -A && git commit -m "盤前整理 $(TZ=Asia/Taipei date +%F)" && git push
```
遇到任何意外（被擋、格式變了、程式錯誤），在 PITFALLS.md 追加一行「日期｜狀況｜怎麼處理」再 commit。
綠燈只代表跑完；結果請打開 reports/ 與 data/<今天>/verify.json 看。
