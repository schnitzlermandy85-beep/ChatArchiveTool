"""Psychology-informed observation lenses, never chat-based psychometrics.

The registry translates selected theories into concrete questions about text
and responses. These are product observation rules, not validated scales or a
method for identifying a person's attachment style or relationship category.
Verified bibliographic references are attached by the integration layer.
"""
from __future__ import annotations

import copy


VERSION = "psychology-frameworks/1"

THEORY_REGISTRY = {
    "family_systems": {
        "id": "family_systems", "name": "家庭系统理论",
        "application": "观察反复的请求—回应循环与家庭事务协调；仅解释这段双人互动。",
        "contextNeeded": ["前后回应及跨情境重复模式", "已明确的家庭身份、其他成员和线下情境"],
        "noInference": ["双人记录不能推断全家结构、代际传递或分化高低", "Bowen的三角涉及至少三人，不能由双人互动推出三角化", "一般角色与边界观察不全归属于Bowen理论"],
    },
    "role_theory": {
        "id": "role_theory", "name": "角色理论",
        "application": "观察双方明确表达的职责、分工、期待及其协商，不预设家庭角色。",
        "contextNeeded": ["当事人明确说明的身份和角色期待", "对职责请求的同意、拒绝及协商上下文"],
        "noInference": ["不能由称呼或一次请求确定权力结构、孝顺程度或固定照护义务"],
    },
    "attachment_theory": {
        "id": "attachment_theory", "name": "依恋理论（亲近寻求与回应视角）",
        "application": "观察压力或分离情境中的亲近寻求与回应；该视角也可用于亲人、伴侣及挚友。",
        "contextNeeded": ["具体情境、请求和后续回应", "不同时间和情境中的互动及当事人感受"],
        "noInference": ["聊天不能诊断安全型、焦虑型或回避型依恋", "一句想你或一次未回不能确定依恋风格或被抛弃恐惧"],
    },
    "triangular_theory_of_love": {
        "id": "triangular_theory_of_love", "name": "Sternberg爱情三角理论",
        "application": "将亲密、激情和决定／承诺作为不同观察问题，不从文字给三者打分。",
        "contextNeeded": ["双方对体验和关系约定的明确表达", "持续互动、线下经历及具体承诺背景"],
        "noInference": ["亲昵称呼不能证明激情、爱情类型或完整爱情", "讨论未来不等于已作出或会履行承诺"],
    },
    "interdependence_theory": {
        "id": "interdependence_theory", "name": "相互依赖理论",
        "application": "观察共同决策、资源和时间协调、彼此影响以及明确表达的期待。",
        "contextNeeded": ["双方选择及协调过程", "现实约束和各自报告的需要与结果"],
        "noInference": ["消息量不能测量依赖强度、满意度、替代选择或退出意图"],
    },
    "gottman_couple_interaction": {
        "id": "gottman_couple_interaction", "name": "Gottman伴侣互动研究",
        "application": "观察冲突中的具体表达、升级与修复尝试，并追踪对方后续回应。",
        "contextNeeded": ["完整冲突过程和前后回应", "语气、非文字信息及重复情境"],
        "noInference": ["单个冷淡词、玩笑或沉默不能定为轻蔑或冷暴力", "不能从聊天预测分手、离婚或修复成功率"],
    },
    "social_exchange_theory": {
        "id": "social_exchange_theory", "name": "社会交换理论",
        "application": "观察互助、负担、期待和公平感的明确表达，不把友情简化为算账。",
        "contextNeeded": ["双方对帮助和负担的具体表述", "较长时间内的需求、能力及情境变化"],
        "noInference": ["不能推断真实利益动机或逐笔相等义务", "回复条数或谢谢的次数不是付出价值"],
    },
    "social_penetration_theory": {
        "id": "social_penetration_theory", "name": "社会渗透理论",
        "application": "观察分享话题的广度与个人化程度，并结合接收方理解、关怀和回应。",
        "contextNeeded": ["分享内容、情境及接收方回应", "跨时间的交流与当事人边界"],
        "noInference": ["秘密更多或表露更深不能直接证明信任更高、关系升级或恋爱倾向"],
    },
    "reciprocity_norm": {
        "id": "reciprocity_norm", "name": "互惠规范",
        "application": "观察帮助和回应如何在时间中协调，区分互惠期待与即时偿还。",
        "contextNeeded": ["长期互助实例和双方明确期待", "当时资源、能力与需要是否不同"],
        "noInference": ["不把不对称消息量、一次拒绝或未即时回报解释为利用或欠债"],
    },
    "communal_exchange_distinction": {
        "id": "communal_exchange_distinction", "name": "关怀性与交换性关系区别",
        "application": "区分按需要提供关怀与明确交换约定，朋友互助不必逐笔对账。",
        "contextNeeded": ["提供帮助时的情境、需要与明确约定", "接受者理解和双方期待"],
        "noInference": ["不能仅凭谢谢、礼物或一次付出给双方关系类型定性"],
    },
    "self_disclosure": {
        "id": "self_disclosure", "name": "自我表露研究",
        "application": "观察主动分享体验及对分享的接纳、理解与隐私边界。",
        "contextNeeded": ["当事人分享意愿及完整回应", "话题背景、保密约定和线下互动"],
        "noInference": ["隐私信息数量不能测量信任，未表露不等于不亲密"],
    },
    "social_support": {
        "id": "social_support", "name": "社会支持与回应性研究",
        "application": "区分倾听、情绪认可、建议和实际帮助，并查看是否符合对方需要。",
        "contextNeeded": ["具体需求、支持方式和接收者反馈", "当时可用资源及后续情境"],
        "noInference": ["谢谢或反复安慰不能单独证明支持有效，建议也不必然代表不关心"],
    },
    "co_rumination": {
        "id": "co_rumination", "name": "共同反刍研究",
        "application": "仅在反复同一问题、持续猜测原因或后果、负面情绪聚焦共同出现时谨慎讨论候选模式。",
        "contextNeeded": ["跨多轮的同一问题讨论、猜测与情绪走向", "是否也在问题解决、澄清新信息及双方感受"],
        "noInference": ["反复倾诉不等于共同反刍", "不预设性别，不推断一定致焦虑、抑郁或关系受损"],
    },
}

DIMENSION_REGISTRY = {
    "proximity_responsiveness": {
        "id": "proximity_responsiveness", "name": "亲近寻求与回应",
        "observable": ["主动表达想交流、需要陪伴或在压力时求助", "对方如何接续请求、说明无法回应或提供其他支持"],
        "alternatives": ["忙碌、作息或其他沟通渠道", "玩笑、惯常称呼或临时情境"],
        "noInference": ["不定依恋风格或亲密强度", "想你或未回不能定安全、焦虑或回避"],
    },
    "roles_expectations": {
        "id": "roles_expectations", "name": "角色义务与期待",
        "observable": ["明确说出的身份、职责、请求与分工", "对期待的同意、拒绝、调整或解释"],
        "alternatives": ["临时安排而非长期义务", "线下协商、文化背景或资源限制"],
        "noInference": ["不由称呼预设性别或家庭角色", "不推断固定权力、孝顺程度或道德价值"],
    },
    "self_disclosure": {
        "id": "self_disclosure", "name": "自我表露与接纳回应",
        "observable": ["主动分享个人体验、担忧及话题范围", "接收方是否理解、关怀、追问及尊重分享边界"],
        "alternatives": ["话题或临时情境促成分享", "隐私偏好、表达习惯或已在线下分享"],
        "noInference": ["表露多少与秘密深浅不是信任分数", "不据此判定关系升级或浪漫意图"],
    },
    "reciprocity": {
        "id": "reciprocity", "name": "互惠与协调",
        "observable": ["跨时间的帮助、接受、回馈及明确期待", "按彼此需要协商投入和负担"],
        "alternatives": ["需要与能力暂时不对称", "关怀性互助、线下付出或不同表达方式"],
        "noInference": ["不逐笔对账或要求消息对半", "不由一次谢谢、拒绝或沉默推断利用、亏欠或利益动机"],
    },
    "boundaries_agreements": {
        "id": "boundaries_agreements", "name": "关系边界与明确约定",
        "observable": ["关于联系、话题、时间、隐私及其他关系的明确表达", "约定是否由双方说明、协商及调整"],
        "alternatives": ["尚未讨论或不同理解", "临时需要、工作安排及文化惯例"],
        "noInference": ["不把排他或独占预设为恋人必要或理想条件", "未经明确约定不判忠诚、不忠、控制欲或真实关系类型"],
    },
    "emotional_support": {
        "id": "emotional_support", "name": "情绪支持与回应方式",
        "observable": ["对烦恼的倾听、认可、建议及实际帮助", "接收者如何表达需要、理解和效果"],
        "alternatives": ["需要倾听或建议的偏好不同", "礼貌、玩笑、误读或缺少线下信息"],
        "noInference": ["谢谢不能证明支持有效，建议不等于不关心", "反复倾诉不能单独定为共同反刍或心理问题"],
    },
    "shared_activities": {
        "id": "shared_activities", "name": "共同活动与协作",
        "observable": ["邀请、共同安排及双方确认", "后续对参与、合作或调整安排的具体反馈"],
        "alternatives": ["工作事务、家庭分工或群体活动", "只是提议，落实情况未知"],
        "noInference": ["聊天邀约不证明活动已发生", "不把共同活动数量当关系质量或浪漫兴趣"],
    },
    "future_commitment": {
        "id": "future_commitment", "name": "未来计划与承诺表达",
        "observable": ["带具体时间或行动的未来安排及明确同意", "对约定的后续反馈、修订和协商"],
        "alternatives": ["愿望、试探、事务计划或客套", "现实约束、线下协商或记录缺失"],
        "noInference": ["不从计划判断真实内心、履约可靠性或终身承诺", "不预测关系升级、分手或关系强度"],
    },
}

_RELATIONSHIPS = {
    "family": {
        "label": "亲人", "primary": "family_systems", "auxiliary": ("role_theory", "attachment_theory"),
        "priority": ("roles_expectations", "boundaries_agreements", "emotional_support", "proximity_responsiveness", "reciprocity", "shared_activities", "self_disclosure", "future_commitment"),
    },
    "partner": {
        "label": "恋人", "primary": "attachment_theory", "auxiliary": ("triangular_theory_of_love", "interdependence_theory", "gottman_couple_interaction"),
        "priority": ("proximity_responsiveness", "emotional_support", "boundaries_agreements", "future_commitment", "self_disclosure", "reciprocity", "shared_activities", "roles_expectations"),
    },
    "friend": {
        "label": "朋友", "primary": "social_exchange_theory", "auxiliary": ("social_penetration_theory", "reciprocity_norm", "communal_exchange_distinction"),
        "priority": ("reciprocity", "shared_activities", "self_disclosure", "emotional_support", "boundaries_agreements", "proximity_responsiveness", "future_commitment", "roles_expectations"),
    },
    "best_friend": {
        "label": "闺蜜／亲密朋友", "primary": "social_penetration_theory", "auxiliary": ("self_disclosure", "social_support", "co_rumination"),
        "priority": ("self_disclosure", "emotional_support", "boundaries_agreements", "reciprocity", "shared_activities", "proximity_responsiveness", "future_commitment", "roles_expectations"),
    },
}

_RULES = (
    "主理论与辅助理论的配置是产品的观察顺序，不是四类关系各有唯一或最优理论的科学定论。",
    "关系类型只是用户选择的分析视角，不能自动判定双方真实关系、性别、家庭角色或是否排他。",
    "每个解释至少对应具体消息行为与前后回应，区分观察和推测，同时给出替代解释；缺少必要情境时明确无法判断。",
    "八个维度是可观察问题而非经过验证的量表；不生成依恋、亲密、忠诚、匹配或关系强度分数，也不画心理评分雷达图。",
    "不得从聊天诊断依恋风格、人格或疾病，推断真实动机，预测关系升级、分手或长期结果。",
    "想你、未回、谢谢或反复倾诉等单句不能直接定安全、焦虑、回避、忠诚、支持有效或共同反刍。",
    "结合接收方回应、情境、重复模式及线下信息缺失；没有某种表达不等于没有相应感受或行为。",
    "按所选视角优先关注相关维度，允许无足够证据的维度无法判断；不得为填满八维编造观察。",
    "仅使用提供且已核验的文献条目；没有来源时不编造作者、研究、引用或因果结论。",
)


def get_framework_profile(relationship):
    """Return a detached, JSON-safe profile for one explicit relationship lens."""
    if not isinstance(relationship, str) or relationship not in _RELATIONSHIPS:
        raise ValueError("心理学视角请选择 family、partner、friend 或 best_friend")
    selected = _RELATIONSHIPS[relationship]
    return {
        "version": VERSION, "relationship": relationship, "relationshipLabel": selected["label"],
        "primaryTheory": copy.deepcopy(THEORY_REGISTRY[selected["primary"]]),
        "auxiliaryTheories": [copy.deepcopy(THEORY_REGISTRY[theory]) for theory in selected["auxiliary"]],
        "priorityDimensions": list(selected["priority"]),
        "dimensionDefinitions": [copy.deepcopy(DIMENSION_REGISTRY[dimension]) for dimension in selected["priority"]],
        "rules": list(_RULES), "references": [],
    }


_PROMPT_DIMENSIONS = {
    "proximity_responsiveness": "观察亲近／陪伴请求与接续回应；考虑忙碌或其他渠道；不定依恋风格、亲密强度。",
    "roles_expectations": "观察明示职责、分工及协商；考虑临时安排或线下约定；不预设角色、权力或道德高低。",
    "self_disclosure": "观察个人分享及接收者理解、关怀与回应；考虑情境与隐私偏好；秘密多少不等于信任或关系升级。",
    "reciprocity": "观察跨时间互助与期待协调；考虑能力不对称、关怀性互助及线下付出；不逐笔对账或推断利益动机。",
    "boundaries_agreements": "观察联系、时间、隐私及关系边界的明确协商；考虑未讨论或不同理解；不预设排他，不判忠诚或控制欲。",
    "emotional_support": "观察倾听、认可、建议、帮助及接收者反馈；考虑需求偏好或误读；谢谢不证明有效，建议不等于不关心。",
    "shared_activities": "观察邀请、确认及后续参与反馈；考虑工作或群体安排；邀约不证明已发生，不换算关系质量或浪漫兴趣。",
    "future_commitment": "观察具体未来安排、明确同意及后续调整；考虑愿望、客套或约束；不判断真实内心、履约可靠性或升级。",
}

_PROMPT_CONTEXT = {
    "family": "家庭视角需重复互动、明确角色与其他成员背景；双人材料不能推断全家结构、代际传递、分化高低或Bowen三角（涉及至少三人）。一般职责与边界观察不全归Bowen。",
    "partner": "伴侣视角需压力情境、请求与回应；依恋研究也涉及亲人及挚友，不能由聊天定安全／焦虑／回避型。Sternberg的亲密、激情、决定／承诺是不同构念，不打分；Gottman修复须看完整冲突与后续回应，不预测分手。",
    "friend": "朋友视角需较长时间互助、双方期待、需要及能力背景；社会交换不等于人人只为利益。关怀性关系按需要支持，区别于明确交换约定，不要求即时偿还或逐笔对账。表露的个人化程度须结合接收方理解关怀，不能视为信任分数。",
    "best_friend": "亲密朋友视角须把个人分享与接收者的理解关怀回应连起来。共同反刍仅在反复同一问题、持续猜测、负面情绪聚焦共同出现时谨慎讨论候选模式；考虑问题解决、新信息和当事人感受。不预设性别，不从反复倾诉断共同反刍或一定致焦虑。",
}


def build_psychology_prompt(profile):
    """Build bounded canonical rules; attached source metadata never becomes instructions."""
    if not isinstance(profile, dict) or profile.get("version") != VERSION:
        raise ValueError("心理学框架配置版本或格式无效")
    canonical = get_framework_profile(profile.get("relationship"))
    primary, auxiliaries = canonical["primaryTheory"], canonical["auxiliaryTheories"]
    lines = [f"【心理学观察框架｜{canonical['relationshipLabel']}】",
             "所选关系仅是观察视角，不能据此分类真实关系或预设性别、家庭角色与独占。理论是解释问题的工具，不是聊天诊断或测量。",
             "主辅框架是产品的观察顺序，不表示理论对某类关系独占适用或最优。",
             "主框架：" + primary["name"] + "。" + primary["application"],
             "辅助框架：" + "；".join(theory["name"] + "：" + theory["application"] for theory in auxiliaries),
             _PROMPT_CONTEXT[canonical["relationship"]],
             "依照以下顺序关注八个可观察维度；每维同时考虑情境和替代解释，证据不足明确无法判断："]
    for dimension in canonical["priorityDimensions"]:
        lines.append(DIMENSION_REGISTRY[dimension]["name"] + "：" + _PROMPT_DIMENSIONS[dimension])
    lines.extend((
        "每条解释至少对应具体行为和前后回应，明确区分事实与推测，给出其他可能解释；缺少上下文、持续模式或当事人感受时说无法判断，不强行填满八维。",
        "双方画像只写这段记录中的表达特点与回应方式；沟通需要写成可询问、可协商的问题，不断言稳定性格、内心需求或心理缺陷。",
        "禁止诊断依恋风格、人格或疾病、推断真实动机、关系升级或长期结果；禁止亲密／依恋／忠诚／匹配／强度分数及心理雷达图。想你、未回、谢谢、反复倾诉等单句不能定安全、焦虑、回避、忠诚或共同反刍。",
        "不把文字中没有某种表达视为没有感受或行为；留出忙碌、线下互动、表达习惯与记录缺失等解释。不编造研究或因果结论。继续遵守既有JSON输出与消息ID校验规则。",
        "框架来源见输入psychologyFramework.references，仅用于说明理论来源；不编造文献，不能把文献当作对本段关系解释成立的证明。",
    ))
    prompt = "\n".join(lines)
    if len(prompt) > 2000:
        raise ValueError("心理学框架提示超过 2000 字符预算")
    return prompt


def psychology_prompt(relationship):
    return build_psychology_prompt(get_framework_profile(relationship))
