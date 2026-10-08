"""Curated theory references, kept separate from model-generated claims."""
from copy import deepcopy


REFERENCES = [
    {"id": "bowen_concepts", "theoryId": "family_systems", "title": "Bowen Center：家庭系统的八个概念", "url": "https://www.thebowencenter.org/introduction-eight-concepts"},
    {"id": "bowen_triangles", "theoryId": "family_systems", "title": "Bowen Center：三人情绪系统", "url": "https://www.thebowencenter.org/triangles"},
    {"id": "fraley_ecr_rs", "theoryId": "attachment_theory", "title": "Fraley：关系结构依恋问卷 ECR-RS", "url": "https://labs.psychology.illinois.edu/~rcfraley/measures/relstructures.htm"},
    {"id": "sternberg_triangle", "theoryId": "triangular_theory_of_love", "title": "Sternberg：爱情三角理论原论文", "url": "https://pzacad.pitzer.edu/~dmoore/1986_Sternberg_TriangleLove_PsyRev.pdf"},
    {"id": "apa_social_exchange", "theoryId": "social_exchange_theory", "title": "APA 心理学词典：社会交换理论", "url": "https://dictionary.apa.org/social-exchange-theory"},
    {"id": "apa_social_penetration", "theoryId": "social_penetration_theory", "title": "APA 心理学词典：社会渗透理论", "url": "https://dictionary.apa.org/social-penetration-theory"},
    {"id": "clark_mills_communal", "theoryId": "communal_exchange_distinction", "title": "Clark 与 Mills：关怀性关系和交换性关系", "url": "https://clarkrelationshiplab.yale.edu/sites/default/files/files/ClarkMills2012.pdf"},
    {"id": "laurenceau_intimacy", "theoryId": "self_disclosure", "title": "Laurenceau 等：自我表露、回应与亲密过程", "url": "https://pubmed.ncbi.nlm.nih.gov/9599440/"},
    {"id": "rose_coruminating", "theoryId": "co_rumination", "title": "Rose 等：共同反刍与友谊、情绪适应的纵向研究", "url": "https://pubmed.ncbi.nlm.nih.gov/17605532/"},
    {"id": "gottman_conflict", "theoryId": "gottman_couple_interaction", "title": "Gottman Institute：冲突互动模式与修复", "url": "https://www.gottman.com/blog/the-four-horsemen-recognizing-criticism-contempt-defensiveness-and-stonewalling-/"},
]


def get_references(theory_ids):
    allowed = set(theory_ids)
    return deepcopy([item for item in REFERENCES if item["theoryId"] in allowed])
