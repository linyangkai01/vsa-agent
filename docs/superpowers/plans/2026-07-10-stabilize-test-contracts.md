---
archived-with: 2026-07-11-stabilize-test-contracts
status: final
---
﻿---
change: stabilize-test-contracts
design-doc: docs/superpowers/specs/2026-07-10-stabilize-test-contracts-design.md
base-ref: 398294a5f0a28fcf1c1284109e8a4ab43ccf8a03
---

# 娴嬭瘯濂戠害绋冲畾鍖?Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [x]) syntax for tracking.

**Goal:** 璁╂姤鍛婃祦绋嬫祴璇曚笉渚濊禆杈撳嚭璇█锛屽苟璁?DashScope 缂哄け API Key 濂戠害鍦ㄦ湰鍦扮幆澧冨拰 Bash 涓ǔ瀹氬彲楠岃瘉銆?
**Architecture:** 鎶ュ憡鐢熸垚鍣ㄤ繚鎸佷笉鍙橈紝楠屾敹娴嬭瘯浠呬粠 Markdown 鏍囬灞傜骇銆佸尯娈甸『搴忓拰杈撳叆鏁版嵁鎺ㄥ璇箟銆傜己澶卞瘑閽ユ祴璇曟樉寮忕鐢ㄦ湰鍦伴厤缃紱涓や釜 Bash 杩愯鍣ㄥ湪 conda/Python 閰嶇疆瑙ｆ瀽鍓嶆鏌ョ幆澧冨彉閲忓苟杩斿洖鏃㈠畾閿欒鐮併€?
**Tech Stack:** Python銆乸ytest銆乸ytest-anyio銆丅ash銆丳owerShell銆丱penSpec銆?
## Global Constraints

- 鎶ュ憡鏍囬璇█涓嶆槸濂戠害锛涢獙鏀舵祴璇曚笉寰楁瘮杈冩爣棰樻枃鏈€?- 鐢熶骇涓繚鐣?config.local.yaml 鍚堝苟锛涙祴璇曚娇鐢?VSA_LOCAL_CONFIG="" 绂佺敤瀹冦€?- config doctor 鏃?Key 杩斿洖 1锛汥ashScope Bash 杩愯鍣ㄦ棤 Key 杩斿洖 2銆?- 鏉′欢璺宠繃蹇呴』淇濈暀锛屼慨鏀圭殑 Shell 鏂囦欢蹇呴』淇濇寔 LF 琛屽熬銆?- 鍏ㄩ噺 pytest 浣跨敤宸ヤ綔鍖哄唴鐨?TEMP 涓?TMP銆?
---

### Task 1: 鎶ュ憡娴佺▼璇箟鏂█

**Files:**
- Modify: tests/acceptance/test_phase6_report_postprocessing_flow.py
- Modify: tests/acceptance/test_report_flow.py
- Test: 涓婅堪涓や釜娴嬭瘯鏂囦欢鍜?tests/unit/tools/test_video_report_gen.py

**Interfaces:**
- Consumes: AgentOutput.side_effects["markdown_content"]: str銆?- Produces: 涓嶄緷璧栨湰鍦板寲鏍囬鏂囨湰鐨勬祦绋嬫祴璇曪紱涓嶆柊澧炵敓浜ф帴鍙ｃ€?
- [x] **Step 1: 鍦ㄤ袱涓祴璇曟枃浠朵腑鍔犲叆澶辫触鐨勬爣棰樺眰绾ц緟鍔╁嚱鏁?*

~~~
def _heading_levels(markdown_content: str) -> list[int]:
    return [
        len(line) - len(line.lstrip("#"))
        for line in markdown_content.splitlines()
        if line.startswith("#") and line.lstrip("#").startswith(" ")
    ]
~~~

- [x] **Step 2: 鐢ㄤ互涓嬪崟瑙嗛鏂█鏇挎崲鎵€鏈変腑鏂囨爣棰樻柇瑷€**

~~~
markdown = result.side_effects["markdown_content"]
assert _heading_levels(markdown) == [1, 2, 2, 2, 2]
assert "video.mp4" in markdown
assert "鐢熸垚璇︾粏鎶ュ憡" in markdown
assert "person walking near forklift" in markdown
assert "[00:00:05 - 00:00:09]" in markdown
~~~

鏍￠獙澶辫触娴佷娇鐢?heading levels [1, 2, 2, 2, 2, 2] 骞舵柇瑷€ VALIDATION_FEEDBACK锛涘瑙嗛娴佷娇鐢?[1, 2, 3, 3]锛屽苟鏂█ camera-1銆乿ideo-a.mp4 鍜屼袱涓?person walking 鎻忚堪瀛樺湪銆?
- [x] **Step 3: 鍏堣繍琛屼互纭鏃у瓧闈㈡柇瑷€浼氭毚闇茶瑷€鑰﹀悎**

Run: python -m pytest tests/acceptance/test_phase6_report_postprocessing_flow.py tests/acceptance/test_report_flow.py -q

Expected: 鏃т腑鏂囨爣棰樻柇瑷€鍦ㄥ綋鍓嶈嫳鏂囨姤鍛婅緭鍑轰笂澶辫触銆?
- [x] **Step 4: 瀹屾垚鏈€灏忔祴璇曚慨鏀瑰苟杩愯鑱氱劍缁?*

Run: python -m pytest tests/acceptance/test_phase6_report_postprocessing_flow.py tests/acceptance/test_report_flow.py tests/unit/tools/test_video_report_gen.py -q

Expected: PASS锛涗簨浠躲€佸弽棣堝拰涓嬭浇鍏冩暟鎹鐩栦粛鍦ㄣ€?
- [x] **Step 5: 鎻愪氦鏈换鍔?*

Run: git add tests/acceptance/test_phase6_report_postprocessing_flow.py tests/acceptance/test_report_flow.py
Run: git commit -m "test: remove report language assumptions"

### Task 2: 閰嶇疆鍖荤敓瀛愯繘绋嬮殧绂?
**Files:**
- Modify: tests/unit/test_config.py
- Test: tests/unit/test_config.py::TestRuntimeConfig::test_config_doctor_cli_reports_missing_key

**Interfaces:**
- Consumes: VSA_LOCAL_CONFIG="" 鏄?_resolve_local_config_path() 瀹氫箟鐨勭鐢ㄦ湰鍦拌鐩栬涔夈€?- Produces: config doctor --config config.yaml 鍦ㄦ棤 Key 鏃惰繑鍥?1銆?
- [x] **Step 1: 鍦ㄥけ璐ユ祴璇曠殑瀛愯繘绋嬬幆澧冧腑鍔犲叆闅旂杈撳叆**

~~~
env.pop("DASHSCOPE_API_KEY", None)
env["VSA_PROFILE"] = "dashscope_remote"
env["VSA_LOCAL_CONFIG"] = ""
~~~

- [x] **Step 2: 杩愯鍗曚釜娴嬭瘯**

Run: python -m pytest tests/unit/test_config.py::TestRuntimeConfig::test_config_doctor_cli_reports_missing_key -q

Expected: PASS锛涜繑鍥?1 涓?stdout 鍖呭惈 DASHSCOPE_API_KEY銆?
- [x] **Step 3: 淇濇寔 src/vsa_agent/config.py 涓嶅彉骞惰繍琛岄厤缃粍**

Run: python -m pytest tests/unit/test_config.py -q

Expected: PASS锛涚幇鏈夋湰鍦伴厤缃姞杞芥祴璇曚笉鍙楀奖鍝嶃€?
- [x] **Step 4: 鎻愪氦鏈换鍔?*

Run: git add tests/unit/test_config.py
Run: git commit -m "test: isolate config doctor from local secrets"

### Task 3: DashScope 杩愯鍣ㄦ棤 Key 鍓嶇疆鏉′欢

**Files:**
- Modify: scripts/run_live_acceptance_dashscope.sh
- Modify: scripts/run_live_top_agent_video_dashscope.sh
- Modify: tests/unit/test_dashscope_live_runner.py
- Test: tests/unit/test_dashscope_live_runner.py

**Interfaces:**
- Consumes: DASHSCOPE_API_KEY 鐜鍙橀噺銆?- Produces: 涓や釜鑴氭湰鏃?Key 鏃跺悜 stderr 杈撳嚭 DASHSCOPE_API_KEY 鍜?config.local.yaml 骞惰繑鍥?2锛涙湁 Key 鏃朵粛浼氭墽琛?config doctor 璺緞銆?
- [x] **Step 1: 澧炲姞澶辫触鐨勮剼鏈『搴忔祴璇曪紝骞堕殧绂绘棤 Key 瀛愯繘绋?*

~~~
def _assert_key_guard_precedes_config_resolution(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    guard = 'if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then'
    assert guard in text
    assert text.index(guard) < text.index('conda run -n "${VSA_CONDA_ENV}" python -m vsa_agent config doctor')
~~~

瀵逛袱涓剼鏈皟鐢ㄨ鍑芥暟锛涗袱涓棤 Key 瀛愯繘绋嬫祴璇曞潎鍔犲叆 env["VSA_LOCAL_CONFIG"] = ""銆?
- [x] **Step 2: 杩愯娴嬭瘯纭瀹堝崼缂哄け鎴栭『搴忛敊璇?*

Run: python -m pytest tests/unit/test_dashscope_live_runner.py -q

Expected: 鏂板椤哄簭鏂█澶辫触锛屾垨 Git Bash 鍦ㄦ棫閰嶇疆瑙ｆ瀽璺緞涓繑鍥?1銆?
- [x] **Step 3: 鍦ㄤ袱涓剼鏈殑 CONFIG_PATH 瀛樺湪鎬ф鏌ュ悗鎻掑叆鍚屼竴瀹堝崼**

~~~
if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
  echo "DASHSCOPE_API_KEY is required via environment or ignored config.local.yaml." >&2
  exit 2
fi
~~~

涓嶅緱绉诲姩鎴栧垹闄ょ幇鏈夌殑 conda 妫€鏌ャ€乧onfig doctor銆乧onfig print銆丳ython 閰嶇疆璇诲彇銆佹ā鍨?瑙嗛閫夋嫨鎴栧疄闄呰繍琛屽懡浠ゃ€?
- [x] **Step 4: 杩愯娴嬭瘯涓?Shell 璇硶妫€鏌?*

Run: python -m pytest tests/unit/test_dashscope_live_runner.py -q
Run: bash -n scripts/run_live_acceptance_dashscope.sh
Run: bash -n scripts/run_live_top_agent_video_dashscope.sh

Expected: PASS锛涙湁 Bash 鏃舵棤 Key 杩斿洖 2锛屾棤 Bash 鏃朵繚鎸佹潯浠惰烦杩囷紝涓や釜鑴氭湰璇硶鏈夋晥涓斾繚鐣?LF 琛屽熬銆?
- [x] **Step 5: 鎻愪氦鏈换鍔?*

Run: git add scripts/run_live_acceptance_dashscope.sh scripts/run_live_top_agent_video_dashscope.sh tests/unit/test_dashscope_live_runner.py
Run: git commit -m "fix: stabilize dashscope missing-key runners"

### Task 4: 楠岃瘉涓庡紑鍙戠姸鎬?
**Files:**
- Modify: openspec/changes/stabilize-test-contracts/tasks.md
- Modify: docs/DEVELOPMENT_STATUS.md
- Test: 鍏ㄩ噺 pytest

**Interfaces:**
- Consumes: TEMP 涓?TMP 鎸囧悜 D:\WorkPlace\vsa-agent\.tmp\pytest-full銆?- Produces: 鍙鐜板叏閲忔祴璇曠粨鏋滃強娲诲姩鍙樻洿鐘舵€併€?
- [x] **Step 1: 浣跨敤宸ヤ綔鍖轰复鏃剁洰褰曡繍琛岃仛鐒︾粍**

~~~
$env:TEMP=(Resolve-Path '.tmp\pytest-full').Path
$env:TMP=$env:TEMP
python -m pytest tests/acceptance/test_phase6_report_postprocessing_flow.py tests/acceptance/test_report_flow.py tests/unit/tools/test_video_report_gen.py tests/unit/test_config.py tests/unit/test_dashscope_live_runner.py -q
~~~

Expected: PASS锛涜烦杩囦粎鐢?Bash 鍙敤鎬х瓑鏃㈡湁鏉′欢瑙﹀彂銆?
- [x] **Step 2: 鍦ㄥ悓涓€涓存椂鐩綍杩愯鍏ㄩ噺娴嬭瘯**

~~~
$env:TEMP=(Resolve-Path '.tmp\pytest-full').Path
$env:TMP=$env:TEMP
python -m pytest -q
~~~

Expected: 姝ゅ墠涔濋」澶辫触娑堝け锛屽洓椤硅烦杩囦繚鐣欍€?
- [x] **Step 3: 鏇存柊浠诲姟涓庡紑鍙戠姸鎬?*

灏?tasks.md 鐨?1.1 鑷?3.2 鏀逛负 - [x]銆傚湪 docs/DEVELOPMENT_STATUS.md 璁板綍 stabilize-test-contracts銆佸叏閲忔祴璇曠粺璁″拰鏉′欢璺宠繃缁熻锛涗笉瑕佸垹闄?script-es-runtime-stack 鐨勭姸鎬併€?
- [x] **Step 4: 澶嶆牳骞舵彁浜よ褰?*

Run: git diff --check
Run: git status --short
Run: git add openspec/changes/stabilize-test-contracts/tasks.md docs/DEVELOPMENT_STATUS.md
Run: git commit -m "docs: record stabilized test contracts"

Expected: git diff --check 鏃犺緭鍑猴紱鎻愪氦鍙寘鍚獙璇佺姸鎬佽褰曘€?
## 鑷

- 浠诲姟 1 瑕嗙洊璇█鏃犲叧鎶ュ憡缁撴瀯鍜屽唴瀹癸紱浠诲姟 2 瑕嗙洊闅旂鐨勯厤缃尰鐢燂紱浠诲姟 3 瑕嗙洊涓や釜杩愯鍣ㄧ殑閫€鍑虹爜涓?Key 璺緞锛涗换鍔?4 瑕嗙洊鍏ㄩ噺楠岃瘉鍜屾潯浠惰烦杩囥€?- 璁″垝娌℃湁 TBD銆乀ODO 鎴栨湭瀹氫箟鎺ュ彛銆?- 鎵€鏈夋枃浠惰矾寰勩€佸懡浠ゃ€佺幆澧冨彉閲忓拰閫€鍑虹爜鍧囦笌褰撳墠浠ｇ爜鍜?OpenSpec 涓€鑷淬€?
