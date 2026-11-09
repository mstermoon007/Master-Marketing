"""模板：listTemplates / listPublishedTemplates / getTemplate / createDraft /
updateTemplateRow / deleteTemplateRow / nextVersion / publishTemplate
"""
import re

from .. import db
from .common import BusinessError, audit, require_manager, require_member

# 客户端可写的列白名单，防止越权字段/主键注入（对应方案 R1）
_PATCH_COLUMNS = frozenset({
    "name", "description", "entry_mode", "fields", "scope",
    "effective_from", "version", "status", "template_id", "team_id",
})
_DRAFT_COLUMNS = frozenset({
    "name", "description", "entry_mode", "fields", "scope",
    "effective_from", "version", "status", "template_id", "team_id",
})


def _clean_patch(patch, allowed):
    if not isinstance(patch, dict):
        raise BusinessError("参数错误")
    out = {}
    for k, v in patch.items():
        if k in allowed:
            out[k] = v
    return out


def list_templates(conn, uid, p):
    require_member(conn, uid, p.get("teamId"))
    rows = db.query(
        conn,
        "SELECT * FROM `form_templates` WHERE team_id = %s "
        "ORDER BY template_id ASC, version DESC LIMIT 1000",
        (p.get("teamId"),),
    )
    return db.rows_to_dicts(rows, "form_templates")


def list_published_templates(conn, uid, p):
    require_member(conn, uid, p.get("teamId"))
    rows = db.query(
        conn,
        "SELECT * FROM `form_templates` WHERE team_id = %s AND status = 'published' "
        "ORDER BY version DESC LIMIT 1000",
        (p.get("teamId"),),
    )
    return db.rows_to_dicts(rows, "form_templates")


def get_template(conn, uid, p):
    row = db.get_doc(conn, "form_templates", p.get("id"))
    if not row:
        raise BusinessError("模板不存在")
    # 草稿/归档版本属于管理端未公开内容：普通成员即便拿到 id 也不能预览。
    # 已发布版本本就通过 listPublishedTemplates 对成员可见，保持 require_member。
    if row.get("status") == "published":
        require_member(conn, uid, row["team_id"])
    else:
        require_manager(conn, uid, row["team_id"])
    return row


def create_draft(conn, uid, p):
    payload = p.get("payload") or {}
    if not isinstance(payload, dict):
        raise BusinessError("参数错误")
    team_id = payload.get("team_id")
    if not team_id:
        raise BusinessError("参数错误：team_id 缺失")
    me = require_manager(conn, uid, team_id)

    data = _clean_patch(payload, _DRAFT_COLUMNS)
    data["created_by"] = me["user_id"]
    data["created_at"] = db.now_iso()
    # 草稿只能以 draft 创建，发布必须走 publishTemplate（防止绕过归档/审计）
    data["status"] = "draft"
    data["fields"] = data.get("fields") or []
    data["scope"] = data.get("scope") or {"type": "all"}
    new_id = db.insert(conn, "form_templates", data)
    audit(conn, uid, team_id, "template_create", "form_templates",
          data.get("template_id"), {"name": data.get("name"), "version": data.get("version")})
    return dict(data, id=new_id)


def update_template_row(conn, uid, p):
    row = db.get_doc(conn, "form_templates", p.get("id"))
    if not row:
        raise BusinessError("模板不存在")
    require_manager(conn, uid, row["team_id"])
    patch = _clean_patch(p.get("patch"), _PATCH_COLUMNS)
    # 主键、归属、版本不允许通过 patch 改写
    for protected in ("id", "team_id", "template_id", "version"):
        patch.pop(protected, None)

    is_archive = len(patch) == 1 and patch.get("status") == "archived"
    if "status" in patch and not is_archive:
        # 发布必须走 publishTemplate，禁止客户端直接改成 published
        raise BusinessError("状态变更请通过发布/停用操作完成")
    if row["status"] == "published" and not is_archive:
        # 旧云函数会在此拦截"停用"，导致管理端停用功能不可用，此处放行停用
        raise BusinessError("已发布的模板不可编辑，请创建新版本")
    if not patch:
        return row
    db.update(conn, "form_templates", p.get("id"), patch)
    return dict(row, **patch)


def delete_template_row(conn, uid, p):
    row = db.get_doc(conn, "form_templates", p.get("id"))
    if not row:
        raise BusinessError("模板不存在")
    require_manager(conn, uid, row["team_id"])
    if row["status"] == "published":
        raise BusinessError("已发布的模板不可删除")
    db.remove(conn, "form_templates", p.get("id"))
    return {"removed": p.get("id")}


def next_version(conn, uid, p):
    require_manager(conn, uid, p.get("teamId"))
    row = db.one(
        conn,
        "SELECT version FROM `form_templates` WHERE team_id = %s AND template_id = %s "
        "ORDER BY version DESC LIMIT 1",
        (p.get("teamId"), p.get("templateId")),
    )
    return int(row["version"]) + 1 if row else 1


def _resolve_version(conn, row):
    """两个管理员同时基于同一版本建草稿会拿到相同 version，发布时撞唯一键。

    调用方需先对团队行加 FOR UPDATE 锁（同一团队的发布串行化），
    此处再检查冲突并把当前草稿顺延到 MAX(version)+1。
    """
    version = int(row.get("version") or 1)
    conflict = db.one(
        conn,
        "SELECT id FROM `form_templates` WHERE team_id = %s AND template_id = %s "
        "AND version = %s AND id <> %s LIMIT 1",
        (row["team_id"], row["template_id"], version, row["id"]),
    )
    if not conflict:
        return version
    mx = db.one(
        conn,
        "SELECT MAX(version) AS v FROM `form_templates` "
        "WHERE team_id = %s AND template_id = %s",
        (row["team_id"], row["template_id"]),
    )
    return max(int(mx["v"] or 0) + 1, version + 1)


def publish_template(conn, uid, p):
    row = db.get_doc(conn, "form_templates", p.get("id"))
    if not row:
        raise BusinessError("模板不存在")
    me = require_manager(conn, uid, row["team_id"])
    if row["status"] != "draft":
        raise BusinessError("只有草稿可以发布")

    # 锁团队行：并发发布串行化，随后的版本号判定与归档才不会互相踩踏
    locked_team = db.one(
        conn, "SELECT id FROM `teams` WHERE team_id = %s FOR UPDATE", (row["team_id"],)
    )
    if not locked_team:
        raise BusinessError("团队不存在或数据异常，无法发布模板")
    version = _resolve_version(conn, row)

    # 保留管理员在草稿里设定的生效日期（未来生效是合法需求）；
    # 前端传的 today 仅作兜底，避免本地时区差异造成空值。
    today = row.get("effective_from") or p.get("today")
    if today and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(today)):
        raise BusinessError("生效日期格式不正确")
    now = db.now_iso()
    db.update(conn, "form_templates", p.get("id"), {
        "status": "published",
        "version": version,
        "effective_from": today,
        "published_by": me["user_id"],
        "published_at": now,
    })

    others = db.query(
        conn,
        "SELECT id FROM `form_templates` "
        "WHERE team_id = %s AND template_id = %s AND status = 'published'",
        (row["team_id"], row["template_id"]),
    )
    for other in others:
        if str(other["id"]) != str(p.get("id")):
            db.update(conn, "form_templates", other["id"], {"status": "archived"})

    audit(conn, uid, row["team_id"], "template_publish", "form_templates",
          row["template_id"], {
              "version": version,
              "fields": row.get("fields"),
              "scope": row.get("scope"),
              "effectiveFrom": today,
              "by": me["user_id"],
          })
    return dict(row, version=version, status="published", effective_from=today,
                published_by=me["user_id"], published_at=now)


HANDLERS = {
    "listTemplates": list_templates,
    "listPublishedTemplates": list_published_templates,
    "getTemplate": get_template,
    "createDraft": create_draft,
    "updateTemplateRow": update_template_row,
    "deleteTemplateRow": delete_template_row,
    "nextVersion": next_version,
    "publishTemplate": publish_template,
}
