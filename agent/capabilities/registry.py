from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from contracts.capability import CapabilityRisk, CapabilitySpec, CapabilityTarget

from ..toolkit.registry import TOOL_SCHEMAS


@dataclass(frozen=True)
class CapabilityGroup:
    profile: str
    domain: str
    execution_target: CapabilityTarget
    risk_level: CapabilityRisk
    tool_names: frozenset[str]
    keywords: tuple[str, ...]
    tags: tuple[str, ...] = ()


GROUPS = (
    CapabilityGroup(
        "workspace_read",
        "workspace",
        CapabilityTarget.LOCAL_TOOLKIT,
        CapabilityRisk.READ,
        frozenset(
            {
                "list_files",
                "read_file",
                "search_files",
                "preview_file_head",
                "get_workspace_summary",
                "count_files_by_extension",
            }
        ),
        (
            "file",
            "files",
            "read",
            "list",
            "search",
            "preview",
            "readme",
            "workspace",
            "directory",
            "count",
            "inspect",
            "文件",
            "目录",
            "读取",
            "查看",
            "搜索",
            "预览",
            "工作区",
            "统计",
            "项目结构",
        ),
        ("read_only",),
    ),
    CapabilityGroup(
        "workspace_write",
        "workspace",
        CapabilityTarget.LOCAL_TOOLKIT,
        CapabilityRisk.WRITE,
        frozenset({"write_file", "append_file", "create_folder"}),
        ("write", "append", "create folder", "写入", "追加", "创建文件", "创建目录"),
        ("mutating",),
    ),
    CapabilityGroup(
        "command",
        "command",
        CapabilityTarget.LOCAL_TOOLKIT,
        CapabilityRisk.EXECUTE,
        frozenset({"run_command"}),
        ("command", "pytest", "python version", "terminal", "命令", "终端", "运行测试"),
    ),
    CapabilityGroup(
        "memory",
        "memory",
        CapabilityTarget.AGENT_STATE,
        CapabilityRisk.CONTROL,
        frozenset({"remember_memory", "read_memory", "clear_memory"}),
        ("memory", "remember", "forget", "记忆", "记住", "忘记"),
    ),
    CapabilityGroup(
        "task",
        "task",
        CapabilityTarget.AGENT_STATE,
        CapabilityRisk.CONTROL,
        frozenset(
            {
                "create_task",
                "list_tasks",
                "get_task_details",
                "start_task",
                "complete_task",
                "fail_task",
                "retry_task",
                "cancel_task",
                "update_task",
            }
        ),
        ("task", "todo", "任务", "待办"),
    ),
    CapabilityGroup(
        "skill",
        "skill",
        CapabilityTarget.AGENT_STATE,
        CapabilityRisk.READ,
        frozenset({"list_skills", "read_skill"}),
        ("skill", "skills", "技能"),
    ),
    CapabilityGroup(
        "event",
        "event",
        CapabilityTarget.AGENT_STATE,
        CapabilityRisk.READ,
        frozenset({"get_recent_tool_events"}),
        ("tool event", "events", "trace", "log", "工具事件", "调用轨迹", "日志"),
    ),
    CapabilityGroup(
        "approval",
        "approval",
        CapabilityTarget.AGENT_STATE,
        CapabilityRisk.CONTROL,
        frozenset(
            {
                "request_overwrite_file",
                "request_edit_file",
                "approve_pending_action",
                "cancel_pending_action",
                "list_pending_approvals",
                "list_approval_history",
                "get_approval_details",
            }
        ),
        ("approval", "approve", "overwrite", "edit", "pending action", "审批", "批准", "覆写", "覆盖", "编辑"),
    ),
    CapabilityGroup(
        "planning",
        "planning",
        CapabilityTarget.AGENT_STATE,
        CapabilityRisk.CONTROL,
        frozenset(
            {
                "create_plan",
                "create_task_plan",
                "get_task_plan",
                "validate_task_plan",
                "run_task_cycle",
                "list_plans",
                "update_plan_step",
                "suggest_next_plan_step",
                "execute_plan_step",
                "execute_next_plan_step",
                "resolve_blocked_step",
                "diagnose_blocked_step",
            }
        ),
        (
            "plan",
            "step",
            "planning",
            "run task",
            "full cycle",
            "计划",
            "步骤",
            "规划",
            "完整任务",
            "全流程",
            "阻塞",
            "诊断",
        ),
    ),
    CapabilityGroup(
        "experiment",
        "experiment",
        CapabilityTarget.AGENT_STATE,
        CapabilityRisk.WRITE,
        frozenset({"save_experiment_note"}),
        ("experiment", "experiment note", "实验", "实验记录"),
    ),
    CapabilityGroup(
        "robot_observe",
        "robot",
        CapabilityTarget.ROBOT_GATEWAY,
        CapabilityRisk.READ,
        frozenset({"robot_get_status", "robot_get_action_status", "robot_capture_image"}),
        ("robot", "robot status", "action status", "camera", "机器人", "机器状态", "动作状态", "相机", "拍照"),
        ("observation",),
    ),
    CapabilityGroup(
        "robot_motion",
        "robot",
        CapabilityTarget.ROBOT_GATEWAY,
        CapabilityRisk.MOTION,
        frozenset({"robot_move", "robot_rotate", "robot_execute_plan",
                   "duck_walk", "duck_kick", "duck_roulade", "duck_ground_pick"}),
        (
            "robot move",
            "move forward",
            "move backward",
            "rotate",
            "turn",
            "机器人移动",
            "移动机器人",
            "向前移动",
            "向后移动",
            "前进",
            "后退",
            "旋转",
            "转向",
            "鸭子",
            "走路",
            "踢球",
            "翻滚",
            "捡东西",
            "duck",
            "walk",
            "kick",
            "roulade",
            "ground pick",
        ),
        ("physical_action",),
    ),
    CapabilityGroup(
        "robot_control",
        "robot",
        CapabilityTarget.ROBOT_GATEWAY,
        CapabilityRisk.CONTROL,
        frozenset({"robot_stop", "robot_cancel_action", "robot_emergency_stop", "robot_speak",
                   "duck_stop", "duck_sit", "duck_head", "duck_body_pose"}),
        (
            "robot stop",
            "stop the robot",
            "emergency stop",
            "cancel action",
            "robot speak",
            "机器人停止",
            "停止机器人",
            "急停",
            "取消动作",
            "机器人说话",
            "坐下",
            "蹲下",
            "站立",
            "头部",
            "身体姿态",
            "sit",
            "stand",
            "head",
            "body pose",
        ),
        ("physical_control",),
    ),
    CapabilityGroup(
        "mobile_observe",
        "robot",
        CapabilityTarget.ROBOT_GATEWAY,
        CapabilityRisk.READ,
        frozenset({"slam_get_pose", "nav_list_places", "vision_verify"}),
        ("slam", "pose", "places", "map", "vision", "verify", "camera", "定位", "地图", "位置", "视觉", "验证", "相机"),
        ("observation",),
    ),
    CapabilityGroup(
        "mobile_manipulation",
        "robot",
        CapabilityTarget.ROBOT_GATEWAY,
        CapabilityRisk.MOTION,
        frozenset({"nav_go_to_place", "vla_run_skill"}),
        ("navigate", "go to", "fetch", "vla", "grasp", "pick up", "fridge", "kitchen",
         "导航", "去", "拿", "取", "冰箱", "厨房", "抓取"),
        ("physical_action",),
    ),
    CapabilityGroup(
        "remote_service",
        "service",
        CapabilityTarget.REMOTE_SERVICE,
        CapabilityRisk.EXECUTE,
        frozenset({"invoke_remote_service"}),
        (
            "remote service",
            "external service",
            "external software",
            "call service",
            "远程服务",
            "外部服务",
            "外部软件",
            "调用服务",
        ),
        ("network", "configured_endpoint"),
    ),
    CapabilityGroup(
        "perception",
        "perception",
        CapabilityTarget.REMOTE_SERVICE,
        CapabilityRisk.READ,
        frozenset({"perception_observe", "perception_check_path"}),
        (
            "perception",
            "observe environment",
            "check path",
            "path clear",
            "obstacle",
            "safe to move",
            "感知",
            "观察环境",
            "检查路径",
            "前方环境",
            "障碍物",
            "是否安全",
        ),
        ("observation", "network", "configured_endpoint"),
    ),
)


PROFILE_DEPENDENCIES = {
    "workspace_write": frozenset({"workspace_read", "approval"}),
    "robot_motion": frozenset({"robot_observe", "robot_control", "perception"}),
    "robot_control": frozenset({"robot_observe"}),
}


class CapabilityRegistry:
    def __init__(self, tool_schemas: Iterable[dict[str, object]]) -> None:
        self._schemas = tuple(tool_schemas)
        self._schema_by_name = {
            str(schema["function"]["name"]): schema
            for schema in self._schemas
        }
        self._group_by_tool = self._build_group_index()
        missing = set(self._schema_by_name) - set(self._group_by_tool)
        extra = set(self._group_by_tool) - set(self._schema_by_name)
        if missing or extra:
            raise ValueError(
                "Capability catalog does not match tool registry: "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        self._spec_by_name = {
            name: self._build_spec(name, schema)
            for name, schema in self._schema_by_name.items()
        }
        self._spec_by_capability_name = {
            spec.name: spec for spec in self._spec_by_name.values()
        }

    def all(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self._spec_by_name[name] for name in self._schema_by_name)

    def get(self, tool_name: str) -> CapabilitySpec:
        try:
            return self._spec_by_name[tool_name]
        except KeyError as exc:
            raise KeyError(f"Unknown capability tool: {tool_name}") from exc

    def get_by_name(self, capability_name: str) -> CapabilitySpec:
        try:
            return self._spec_by_capability_name[capability_name]
        except KeyError as exc:
            raise KeyError(f"Unknown capability: {capability_name}") from exc

    def select(self, text: str) -> tuple[CapabilitySpec, ...]:
        profiles = self._matched_profiles(text)
        if not profiles:
            return self.all()
        expanded = set(profiles)
        for profile in tuple(profiles):
            expanded.update(PROFILE_DEPENDENCIES.get(profile, ()))
        selected_names = {
            tool_name
            for group in GROUPS
            if group.profile in expanded
            for tool_name in group.tool_names
        }
        return tuple(
            self._spec_by_name[name]
            for name in self._schema_by_name
            if name in selected_names
        )

    def schemas_for_text(self, text: str) -> list[dict[str, object]]:
        names = {spec.tool_name for spec in self.select(text)}
        return [schema for name, schema in self._schema_by_name.items() if name in names]

    def schemas_for_names(self, tool_names: Iterable[str]) -> list[dict[str, object]]:
        names = frozenset(tool_names)
        unknown = names - set(self._schema_by_name)
        if unknown:
            raise ValueError(f"Unknown capability tools: {', '.join(sorted(unknown))}")
        return [schema for name, schema in self._schema_by_name.items() if name in names]

    def prompt_summary(self, specs: Iterable[CapabilitySpec]) -> str:
        rows = ["Capabilities selected for this execution:"]
        rows.extend(
            f"- {spec.tool_name}: domain={spec.domain}, target={spec.execution_target.value}, risk={spec.risk_level.value}"
            for spec in sorted(specs, key=lambda item: item.tool_name)
        )
        return "\n".join(rows)

    def _build_group_index(self) -> dict[str, CapabilityGroup]:
        result: dict[str, CapabilityGroup] = {}
        for group in GROUPS:
            for name in group.tool_names:
                if name in result:
                    raise ValueError(f"Tool belongs to multiple capability groups: {name}")
                result[name] = group
        return result

    def _build_spec(self, name: str, schema: dict[str, object]) -> CapabilitySpec:
        function = schema["function"]
        group = self._group_by_tool[name]
        return CapabilitySpec(
            name=f"{group.domain}.{name}",
            description=str(function.get("description", "")),
            domain=group.domain,
            execution_target=group.execution_target,
            risk_level=group.risk_level,
            tool_name=name,
            input_schema=dict(function.get("parameters", {})),
            tags=(group.profile, *group.tags),
        )

    def _matched_profiles(self, text: str) -> set[str]:
        normalized = text.strip().lower()
        if not normalized:
            return set()
        return {
            group.profile
            for group in GROUPS
            if any(_contains_keyword(normalized, keyword) for keyword in group.keywords)
        }


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized = keyword.lower()
    if normalized.isascii():
        return re.search(rf"(?<![a-z0-9_]){re.escape(normalized)}(?![a-z0-9_])", text) is not None
    return normalized in text


CAPABILITY_REGISTRY = CapabilityRegistry(TOOL_SCHEMAS)
