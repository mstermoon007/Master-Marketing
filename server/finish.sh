#!/usr/bin/env bash
# 报数机器人AI · 静态验证（只验证，不修改任何文件）
#
# 用法（在项目根目录执行；其它目录执行也可以，脚本会自行 cd 到项目根）：
#   bash server/finish.sh
#   bash server/finish.sh --verify-only   # 兼容旧用法，等价
#
# 背景：云开发残留文件已于 2026-11-09 物理删除，本脚本不再包含删除逻辑。
#
# 兼容性：macOS 自带 bash 3.2，未使用 mapfile / 关联数组 / ${var^^}。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

case "${1:-}" in
  ""|--verify-only) ;;
  *) echo "未知参数：$1（本脚本只做验证，无需其它参数）"; exit 2 ;;
esac

FAIL=0
DEPS_MISSING=0
note_fail() { FAIL=1; }

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

# 注：前后端 action 名称逐一对应由 server/tests/test_contract.py 负责，
# 此处不再用正则二次校验（旧正则会把字典键误判为 action）。

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
    --exclude-dir=.workbuddy --exclude-dir=.codebuddy --exclude-dir=.agents \
    --exclude-dir=.venv --exclude-dir=.git --exclude='finish.sh' \
    . 2>/dev/null; then
  echo "  ↑ 旧名称仍有命中，请人工确认"
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

echo
if [ "$FAIL" -eq 0 ]; then
  echo "=== 完成：验证全部通过 ==="
else
  echo "=== 完成：存在失败项，见上方 ↑ ==="
fi
echo "部署迁移：server/sql/migrate_p2_report_tasks.sql → server/sql/migrate_p3_analysis.sql → server/sql/migrate_p4_workspaces.sql → server/sql/migrate_p5_web_tickets.sql"
exit "$FAIL"
