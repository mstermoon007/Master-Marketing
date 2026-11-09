#!/usr/bin/env bash
# 报数机器人AI · 无效文件清理 + 静态验证（一次性脚本，可重复运行）
#
# 用法（在项目根目录执行；从任意目录执行也可以，脚本会自行 cd 到项目根）：
#   bash server/finish.sh                 列清单 → 输入 yes → 删除 + 全套验证
#   bash server/finish.sh --yes           跳过确认，直接删除 + 全套验证
#   bash server/finish.sh --verify-only   只跑验证，一个文件都不删
#
# 背景：会话环境无命令行/删除能力，仓库里的云开发残留文件已先被「内容中和」
#      （清空实现、去掉旧名称与 CloudBase 引导、被 packOptions 排除、不进小程序包）。
#      即使不执行本脚本也无害；执行它是为了彻底移除文件并跑 Python/JS 验证。
#
# 兼容性：macOS 自带 bash 3.2，未使用 mapfile / 关联数组 / ${var^^}。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

MODE="normal"
case "${1:-}" in
  --yes) MODE="yes" ;;
  --verify-only) MODE="verify" ;;
  "") ;;
  *) echo "未知参数：$1（可用：--yes / --verify-only）"; exit 2 ;;
esac

FILES=(
  "utils/cloud.js"
  "utils/cloud-config.js"
  "cloudbaserc.json"
  "cloudfunctions/login/index.js"
  "cloudfunctions/login/package.json"
  "cloudfunctions/api/index.js"
  "cloudfunctions/api/package.json"
  ".cloudbase/container/debug.json"
)
# 注意：CODEBUDDY.md 已改写为「自有服务端开发约定」，是防止后续开发
#       被带回云函数路径的关键入口，属于保留项，绝不删除。
DIRS=(
  "cloudfunctions/login"
  "cloudfunctions/api"
  "cloudfunctions"
  ".cloudbase/container"
  ".cloudbase"
  "rules"
  "codebuddy-plugin"
)

FAIL=0
DEPS_MISSING=0
note_fail() { FAIL=1; }

if [ "$MODE" != "verify" ]; then
  echo "=== 待删除的无效文件 ==="
  for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then echo "  $f"; else echo "  (不存在，跳过) $f"; fi
  done
  echo "=== 待删除的无效目录（整目录，均为 CloudBase 脚手架残留）==="
  for d in "${DIRS[@]}"; do
    if [ -d "$d" ]; then echo "  $d/"; else echo "  (不存在，跳过) $d/"; fi
  done
  echo
  echo "[注意] 以上删除后不可恢复。保留项：.workbuddy/、*.genie、*.privacy.json、"
  echo "        project.private.config.json、sitemap.json、CODEBUDDY.md（已改写为项目约定）、"
  echo "        docs/、server/ 全部源码。"
  echo "        可选手动清理（IDE 技能副本，不影响构建）：.codebuddy/skills/  .agents/skills/"

  if [ "$MODE" != "yes" ]; then
    ans=""
    read -r -p "确认删除请输入 yes： " ans || true
    if [ "$ans" != "yes" ]; then echo "已取消，未删除任何文件。"; exit 0; fi
  fi

  echo
  echo "=== 清理 1/2 删除文件 ==="
  for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then rm -f "$f" && echo "  removed $f"; fi
  done
  echo "=== 清理 2/2 删除目录 ==="
  for d in "${DIRS[@]}"; do
    if [ -d "$d" ]; then rm -r "$d" && echo "  removed $d/"; fi
  done
else
  echo "=== --verify-only：跳过删除，仅执行验证 ==="
fi

echo
echo "=== 验证 1/6 Python 依赖预检 ==="
if command -v python3 >/dev/null 2>&1; then
  if python3 -c 'import fastapi, pymysql, jwt, pytest' 2>/dev/null; then
    echo "  fastapi / pymysql / PyJWT / pytest：齐备"
  else
    echo "  缺少依赖 → 请在 server/ 目录执行： pip install -r requirements.txt"
    DEPS_MISSING=1
  fi
else
  echo "  python3 不可用，跳过全部 Python 验证"
  DEPS_MISSING=1
fi

echo "=== 验证 2/6 Python 语法编译（不依赖第三方库）==="
if command -v python3 >/dev/null 2>&1; then
  if python3 -m compileall -q server/app server/tests; then
    echo "  compileall：通过"
  else
    echo "  compileall：有语法错误 ↑"
    note_fail
  fi
else
  echo "  跳过（无 python3）"
fi

echo "=== 验证 3/6 契约与业务流程单测 ==="
if [ "$DEPS_MISSING" -eq 1 ]; then
  echo "  跳过（依赖未安装，先 pip install -r server/requirements.txt）"
else
  if (cd server && python3 -m pytest -q); then
    echo "  pytest：通过"
  else
    echo "  pytest：未通过 ↑"
    note_fail
  fi
fi

echo "=== 验证 4/6 小程序 JS 语法 ==="
if command -v node >/dev/null 2>&1; then
  JS_FAIL=0
  JS_COUNT=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    JS_COUNT=$((JS_COUNT + 1))
    node --check "$f" >/dev/null 2>&1 || { echo "  语法错误: $f"; JS_FAIL=1; }
  done < <(find app.js utils pages components -name '*.js' -type f 2>/dev/null)
  if [ "$JS_FAIL" -eq 0 ]; then
    echo "  node --check：$JS_COUNT 个文件全部通过"
  else
    echo "  node --check：有语法错误 ↑"
    note_fail
  fi
else
  echo "  node 不可用，跳过"
fi

# 注：前后端 action 名称逐一对应由 server/tests/test_contract.py
# 的 test_all_legacy_actions_migrated（验证 3 pytest）负责，此处不再用正则二次校验
# （旧正则会把 audit/insert 调用里的字典键误判为 action，产生误报）。

echo "=== 验证 5/6 残留引用与名称一致性 ==="
if grep -rnE "wx\.cloud\.|require\(['\"]\./cloud['\"]\)|require\(['\"]\./cloud-config['\"]\)" \
    --include='*.js' utils pages components app.js 2>/dev/null; then
  echo "  ↑ 云开发引用仍有命中，请人工确认"
  note_fail
else
  echo "  云开发引用：无残留"
fi
if grep -rnE "今日报数|日工作记录" \
    --include='*.js' --include='*.json' --include='*.wxml' --include='*.wxss' \
    --include='*.md' --include='*.py' --include='*.sql' --include='*.sh' \
    --exclude-dir=.workbuddy --exclude-dir=rules --exclude-dir=codebuddy-plugin \
    --exclude-dir=.codebuddy --exclude-dir=.agents --exclude-dir=.venv \
    --exclude-dir=.git --exclude='finish.sh' \
    . 2>/dev/null; then
  echo "  ↑ 旧名称仍有命中，请人工确认（若为待删残留文件属正常）"
  note_fail
else
  echo "  旧名称：无残留"
fi
if grep -rnE "hasTeam|myTeams|ignoreScope|getActiveTemplate\([^)]*,[^)]*, *true\)" \
    --include='*.js' --include='*.py' utils pages components app.js server/app 2>/dev/null; then
  echo "  ↑ 已清理的死字段/旧口径仍有命中，请人工确认"
  note_fail
else
  echo "  死字段与多模板旧口径：无残留"
fi

echo "=== 验证 6/6 首次启动配置自检（仅提示，不算失败）==="
if [ ! -f server/.env ]; then
  echo "  [待办] server/.env 尚未创建 → cp server/.env.example server/.env 并填 AppID/AppSecret/JWT_SECRET/MySQL"
fi
if grep -q 'api.example.com' utils/config.js 2>/dev/null; then
  echo "  [待办] utils/config.js 的 BASE_URL 仍是占位域名 → 上线前替换为已备案 HTTPS 域名"
fi
if ! grep -rnE "alwaysApply: true" --include='*.md' rules codebuddy-plugin 2>/dev/null | grep -q .; then
  echo "  过时的 CloudBase 自动加载规则：已禁用/已清理"
else
  echo "  [提示] rules/ 下仍有 alwaysApply 规则，建议执行本脚本删除残留目录"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "=== 完成：验证全部通过 ==="
else
  echo "=== 完成：存在失败项，见上方 ↑ ==="
fi
echo "把本输出贴回对话，可按具体报错逐条收尾。"
echo "后续：按 README.md / docs/DEVELOPMENT.md 配置 server/.env 与 utils/config.js 域名。"
echo "本脚本为一次性工具，清理完成后可手动删除：rm server/finish.sh"
exit "$FAIL"
