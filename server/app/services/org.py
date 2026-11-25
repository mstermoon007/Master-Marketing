"""组织与多工作空间：工作空间角色、部门层级与团队访问判定。

约束：
- 所有工作空间/部门/角色判断集中在本模块，handler 不得自行拼装；
- 部门最多 3 级，服务端强制；
- 团队访问 = 团队成员 ∪ 空间 owner/admin ∪ 部门负责人（限其部门子树）。
"""
import secrets
from typing import Dict, List, Optional

from .. import db

MAX_DEPARTMENT_DEPTH = 3

WORKSPACE_ROLES = ("owner", "admin", "member", "viewer")
TEAM_ROLES = ("owner", "manager", "member", "viewer")
WORKSPACE_MANAGER_ROLES = ("owner", "admin")
TEAM_MANAGER_ROLES = ("owner", "manager")


# ---------------------------------------------------------------------------
# 工作空间
# ---------------------------------------------------------------------------
def get_workspace(conn, workspace_id: Optional[str]) -> Optional[dict]:
    if not workspace_id:
        return None
    return db.get_doc(conn, "workspaces", workspace_id)


def find_workspace_by_code(conn, code: Optional[str]) -> Optional[dict]:
    if not code:
        return None
    return db.get_doc_by_field(conn, "workspaces", "workspace_code", code)


def workspace_membership(conn, uid: str, workspace_id: Optional[str]) -> Optional[dict]:
    if not uid or not workspace_id:
        return None
    row = db.one(
        conn,
        "SELECT * FROM `workspace_members` WHERE workspace_id = %s AND user_id = %s LIMIT 1",
        (workspace_id, uid),
    )
    return db.row_to_dict(row, "workspace_members")


def workspace_role(conn, uid: str, workspace_id: Optional[str], active_only: bool = True) -> Optional[str]:
    row = workspace_membership(conn, uid, workspace_id)
    if not row:
        return None
    if active_only and row.get("status") != "active":
        return None
    return row.get("role")


def list_workspace_members(conn, workspace_id: str) -> List[dict]:
    rows = db.query(
        conn,
        "SELECT * FROM `workspace_members` WHERE workspace_id = %s ORDER BY joined_at ASC, id ASC",
        (workspace_id,),
    )
    return db.rows_to_dicts(rows, "workspace_members")


def workspaces_of_user(conn, uid: str) -> List[dict]:
    """返回我加入的空间（附带 workspace_role），按加入时间升序。"""
    rows = db.query(
        conn,
        "SELECT w.*, wm.role AS workspace_role, wm.status AS workspace_member_status "
        "FROM `workspace_members` wm JOIN `workspaces` w ON w.id = wm.workspace_id "
        "WHERE wm.user_id = %s AND wm.status = 'active' "
        "ORDER BY wm.joined_at ASC, w.id ASC",
        (uid,),
    )
    return db.rows_to_dicts(rows, "workspaces")


# ---------------------------------------------------------------------------
# 团队
# ---------------------------------------------------------------------------
def team_context(conn, team_id: Optional[str]) -> Optional[dict]:
    if not team_id:
        return None
    row = db.one(
        conn,
        "SELECT t.*, om.name AS owner_name FROM `teams` t "
        "LEFT JOIN `members` om ON om.team_id = t.team_id AND om.user_id = t.owner_uid "
        "WHERE t.team_id = %s LIMIT 1",
        (team_id,),
    )
    return db.row_to_dict(row, "teams")


def teams_in_workspace(conn, workspace_id: str) -> List[dict]:
    rows = db.query(
        conn,
        "SELECT t.*, om.name AS owner_name FROM `teams` t "
        "LEFT JOIN `members` om ON om.team_id = t.team_id AND om.user_id = t.owner_uid "
        "WHERE t.workspace_id = %s ORDER BY t.created_at ASC, t.id ASC",
        (workspace_id,),
    )
    return db.rows_to_dicts(rows, "teams")


def teams_of_user_in_workspace(conn, uid: str, workspace_id: str) -> List[dict]:
    rows = db.query(
        conn,
        "SELECT t.*, m.role AS member_role, m.status AS member_status, om.name AS owner_name "
        "FROM `teams` t JOIN `members` m ON m.team_id = t.team_id "
        "LEFT JOIN `members` om ON om.team_id = t.team_id AND om.user_id = t.owner_uid "
        "WHERE t.workspace_id = %s AND m.user_id = %s AND m.status = 'active' "
        "ORDER BY t.created_at ASC, t.id ASC",
        (workspace_id, uid),
    )
    return db.rows_to_dicts(rows, "teams")


# ---------------------------------------------------------------------------
# 部门
# ---------------------------------------------------------------------------
def departments_of(conn, workspace_id: str) -> List[dict]:
    rows = db.query(
        conn,
        "SELECT * FROM `departments` WHERE workspace_id = %s ORDER BY depth ASC, created_at ASC, id ASC",
        (workspace_id,),
    )
    return db.rows_to_dicts(rows, "departments")


def department_tree(rows: List[dict]) -> List[dict]:
    """把部门平铺列表组装成树；不修改入参。"""
    children: Dict[str, List[dict]] = {}
    for row in rows:
        node = dict(row)
        node["children"] = []
        children.setdefault(row.get("parent_id") or "", []).append(node)

    def attach(parent_id: str) -> List[dict]:
        nodes = children.get(parent_id, [])
        for node in nodes:
            node["children"] = attach(node["id"])
        return nodes

    return attach("")


def ancestor_ids(rows: List[dict], department_id: Optional[str]) -> List[str]:
    if not department_id:
        return []
    index = {r["id"]: r for r in rows}
    out: List[str] = []
    current: Optional[str] = department_id
    guard = 0
    while current and current in index and guard <= MAX_DEPARTMENT_DEPTH + 1:
        out.append(current)
        current = index[current].get("parent_id")
        guard += 1
    return out


def is_department_leader(conn, uid: str, workspace_id: Optional[str],
                         department_id: Optional[str], rows: Optional[List[dict]] = None) -> bool:
    if not uid or not workspace_id or not department_id:
        return False
    depts = rows if rows is not None else departments_of(conn, workspace_id)
    index = {r["id"]: r for r in depts}
    for did in ancestor_ids(depts, department_id):
        dept = index.get(did) or {}
        if dept.get("leader_uid") == uid and dept.get("status", "active") == "active":
            return True
    return False


def subtree_height(rows: List[dict], root_id: str) -> int:
    """含 root 自身在内的子树高度（叶子为 1）。"""
    children = [r for r in rows if r.get("parent_id") == root_id]
    if not children:
        return 1
    return 1 + max(subtree_height(rows, c["id"]) for c in children)


def validate_new_department_depth(parent: Optional[dict]) -> int:
    depth = 1 if not parent else int(parent.get("depth") or 1) + 1
    if depth > MAX_DEPARTMENT_DEPTH:
        raise ValueError(f"部门最多 {MAX_DEPARTMENT_DEPTH} 级")
    return depth


def validate_move_department(rows: List[dict], department: dict, new_parent: Optional[dict]) -> int:
    """校验移动后层级，返回新的 depth；非法时抛 ValueError。"""
    # 先判环路：新上级若位于本部门子树内（含自身），移动会形成环
    if new_parent and department["id"] in ancestor_ids(rows, new_parent["id"]):
        raise ValueError("不能把部门移动到自己的下级")
    new_depth = validate_new_department_depth(new_parent)
    height = subtree_height(rows, department["id"])
    if new_depth + height - 1 > MAX_DEPARTMENT_DEPTH:
        raise ValueError(f"移动后超过 {MAX_DEPARTMENT_DEPTH} 级")
    return new_depth


# ---------------------------------------------------------------------------
# 统一访问判定
# ---------------------------------------------------------------------------
def effective_role(member: Optional[dict], ws_role: Optional[str], dept_leader: bool) -> Optional[str]:
    """有效角色优先级：团队 owner/manager > 空间 owner/admin > 部门负责人 > 团队/空间普通角色。"""
    if member and member.get("status") == "active" and member.get("role") in TEAM_MANAGER_ROLES:
        return member.get("role")
    if ws_role in WORKSPACE_MANAGER_ROLES:
        return ws_role
    if dept_leader:
        return "manager"
    if member and member.get("status") == "active":
        return member.get("role") or "member"
    if ws_role:
        return ws_role
    return None


def can_read_team(ctx: dict) -> bool:
    return bool(
        ctx.get("is_team_member")
        or ctx.get("workspace_role") in WORKSPACE_MANAGER_ROLES
        or ctx.get("is_department_leader")
    )


def can_manage_team(ctx: dict) -> bool:
    member = ctx.get("member") or {}
    return bool(
        (ctx.get("is_team_member") and member.get("role") in TEAM_MANAGER_ROLES)
        or ctx.get("workspace_role") in WORKSPACE_MANAGER_ROLES
        or ctx.get("is_department_leader")
    )


def can_write_team(ctx: dict) -> bool:
    return can_read_team(ctx) and ctx.get("effective_role") not in (None, "viewer")


def is_workspace_manager(role: Optional[str]) -> bool:
    return role in WORKSPACE_MANAGER_ROLES


# ---------------------------------------------------------------------------
# 创建与成员维护（服务端唯一写入口）
# ---------------------------------------------------------------------------
def gen_workspace_code(conn) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(5):
        code = "W" + "".join(secrets.choice(alphabet) for _ in range(7))
        if not find_workspace_by_code(conn, code):
            return code
    raise ValueError("生成工作空间编码失败")


def role_priority(role: Optional[str]) -> int:
    return {"owner": 4, "admin": 3, "manager": 3, "member": 2, "viewer": 1}.get(role or "", 0)


def create_workspace_record(conn, uid: str, name: str, member_name: str,
                            workspace_code: Optional[str] = None) -> dict:
    """创建空间并把创建者登记为 owner；返回 {workspace, membership}。"""
    now = db.now_iso()
    code = workspace_code or gen_workspace_code(conn)
    if find_workspace_by_code(conn, code):
        raise ValueError(f"工作空间编码已存在：{code}")
    workspace_id = db.insert(conn, "workspaces", {
        "workspace_code": code,
        "name": name,
        "owner_uid": uid,
        "config": {"memberSeeTeamTotal": False},
        "created_at": now,
    })
    membership_id = db.insert(conn, "workspace_members", {
        "workspace_id": workspace_id,
        "user_id": uid,
        "name": member_name,
        "role": "owner",
        "status": "active",
        "joined_at": now,
    })
    return {
        "workspace": {
            "id": workspace_id, "workspace_code": code, "name": name,
            "owner_uid": uid, "config": {"memberSeeTeamTotal": False}, "created_at": now,
        },
        "membership": {
            "id": membership_id, "workspace_id": workspace_id, "user_id": uid,
            "name": member_name, "role": "owner", "status": "active", "joined_at": now,
        },
    }


def ensure_workspace_member(conn, workspace_id: str, uid: str, name: str,
                            role: str = "member") -> dict:
    """加入团队时补齐空间成员；角色只升不降。停用空间成员直接拒绝。"""
    existing = workspace_membership(conn, uid, workspace_id)
    if existing:
        if existing.get("status") != "active":
            raise ValueError("你在该工作空间中已被停用，请联系空间管理员")
        if role_priority(role) > role_priority(existing.get("role")):
            db.update(conn, "workspace_members", existing["id"], {"role": role})
            existing["role"] = role
        return existing
    now = db.now_iso()
    membership_id = db.insert(conn, "workspace_members", {
        "workspace_id": workspace_id,
        "user_id": uid,
        "name": name,
        "role": role,
        "status": "active",
        "joined_at": now,
    })
    return {
        "id": membership_id, "workspace_id": workspace_id, "user_id": uid,
        "name": name, "role": role, "status": "active", "joined_at": now,
    }


def get_department(conn, department_id: Optional[str]) -> Optional[dict]:
    if not department_id:
        return None
    return db.get_doc(conn, "departments", department_id)

