整理一份繁體中文旅遊週摘要。遵循旅遊總指揮官的 SOUL.md。

先讀 `{{ROOT}}/shared/travel-workflow/` 的偏好和機會紀錄，及 `{{ROOT}}/shared/annual-schedule/calendar.json`。用本地終端機執行 `& "{{PYTHON}}" "{{ROOT}}/profiles/travel-commander/scripts/travel-scout.py" --snapshot`，保留日期、掃描時間、價格和幣別。檢查 command-center 上等待查核的卡片並接續可完成的工作。

依出發地、目的地、旅行長度、整趟預算與完整時段篩選候選。必要時請 Trip Agent 補查，並向 Schedule Manager 核對時間。需要住宿和行程建議時載入 travel-planning 技能。提供少量適合考慮的候選，標記時段與費用的核對狀態、來源、查詢時間和下一個決定。沒有合適機會時如實說明。遇到資料缺口時，列出最多兩項影響最大的待確認條件。

訊息會在手機上閱讀：不用表格或程式碼區塊，改用每行一項的條列；第一行寫結論，整則控制在手機一到兩個畫面。需要使用者決定時，結尾寫一句「回覆小居，我會用按鈕讓你選」，不要列一串文字選項。每個條列在手機上最多兩行。送出前用 `& "{{PYTHON}}" "{{ROOT}}/shared/travel-workflow/phone-check.py" --text "<訊息，換行寫成 \n>"` 檢查一次，不是 OK 就改，最多重試兩次。一週內查過的資料直接沿用。
